"""Task management + WebSocket routes."""
from __future__ import annotations

import asyncio
import logging
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse

from app.config import get_settings
from app.models.task import CAMERA_NAMES, Task, TaskParams, TaskStatus, UploadedFile
from app.services.orchestrator import regenerate_view, schedule_task
from app.services.comfy_client import list_wear_models
from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)
router = APIRouter()
ws_router = APIRouter()


@router.get("/workflow-models")
async def get_workflow_models() -> dict:
    return {"items": list_wear_models()}


@router.get("")
async def list_tasks(limit: int = Query(50, ge=1, le=500)) -> dict:
    tasks = await task_manager.list(limit=limit)
    return {"items": [t.model_dump(mode="json") for t in tasks], "total": len(tasks)}


@router.post("", response_model=Task)
async def create_task(payload: dict[str, Any]) -> Task:
    params = TaskParams.model_validate(payload.get("params") or {})
    inputs_raw = payload.get("inputs") or []
    inputs = [UploadedFile.model_validate(i) for i in inputs_raw]
    task = Task(
        name=payload.get("name") or params.name,
        params=params,
        inputs=inputs,
        status=TaskStatus.pending,
    )
    return await task_manager.create(task)


@router.get("/{task_id}", response_model=Task)
async def get_task(task_id: str) -> Task:
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


@router.patch("/{task_id}", response_model=Task)
async def patch_task(task_id: str, payload: dict[str, Any]) -> Task:
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if t.status in {TaskStatus.running, TaskStatus.rendering, TaskStatus.inpainting, TaskStatus.reconstructing}:
        raise HTTPException(status_code=409, detail="任务还在运行中")
    if "name" in payload:
        t.name = payload["name"]
    if "params" in payload and isinstance(payload["params"], dict):
        t.params = TaskParams.model_validate({**t.params.model_dump(), **payload["params"]})
    if "inputs" in payload and isinstance(payload["inputs"], list):
        t.inputs = [UploadedFile.model_validate(i) for i in payload["inputs"]]
    await task_manager.update(t)
    return t


@router.get("/{task_id}/logs", response_class=PlainTextResponse)
async def get_logs(task_id: str, tail: int | None = Query(default=None, ge=1, le=10000)) -> str:
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return await task_manager.read_log(task_id, tail=tail)


@router.post("/{task_id}/run", response_model=Task)
async def run_task(task_id: str) -> Task:
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if t.status in {TaskStatus.running, TaskStatus.rendering, TaskStatus.inpainting, TaskStatus.reconstructing, TaskStatus.awaiting_confirm}:
        raise HTTPException(status_code=409, detail="任务已在运行中")
    if not t.model_input():
        raise HTTPException(status_code=400, detail="请先上传一个 .glb 或 .gltf 3D 模型文件")

    # 预检验证
    from app.services.orchestrator import Orchestrator
    orch = Orchestrator(t)
    issues = await orch._validate(start_from=None)
    if issues:
        raise HTTPException(
            status_code=400,
            detail="启动前检查未通过:\n  " + "\n  ".join(f"• {i}" for i in issues),
        )

    t.status = TaskStatus.queued
    t.error = None
    await task_manager.update(t)
    schedule_task(t)
    return t


@router.post("/{task_id}/retry", response_model=Task)
async def retry_task(task_id: str) -> Task:
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if t.status in {TaskStatus.running, TaskStatus.rendering, TaskStatus.inpainting, TaskStatus.reconstructing, TaskStatus.awaiting_confirm}:
        raise HTTPException(status_code=409, detail="任务已在运行中, 当前无法重试")
    if t.status not in {TaskStatus.failed, TaskStatus.cancelled, TaskStatus.completed}:
        # Stale running state without a live job — rescue + allow retry
        await task_manager.force_reset(task_id)
        t = await task_manager.get(task_id) or t

    start_from = None
    for s in t.stages:
        if s.status != "completed":
            start_from = s.name
            break
    t.status = TaskStatus.queued
    t.error = None
    if start_from:
        target = t.stage(start_from)
        target.status = "pending"
        target.error = None
    await task_manager.update(t)
    schedule_task(t, start_from=start_from)
    return t


@router.post("/{task_id}/continue", response_model=Task)
async def continue_task(task_id: str) -> Task:
    """用户确认 inpaint 结果后, 从 reconstruct 阶段继续。"""
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task_manager.is_job_running(task_id):
        raise HTTPException(status_code=409, detail="任务还在运行中")
    if t.status != TaskStatus.awaiting_confirm:
        raise HTTPException(
            status_code=409,
            detail=f"任务不在等待确认状态 (当前: {t.status.value}), 请完成一次 inpaint 后再确认",
        )
    t.status = TaskStatus.queued
    t.error = None
    rec = t.stage("reconstruct")
    rec.status = "pending"
    rec.error = None
    await task_manager.update(t)
    schedule_task(t, start_from="reconstruct")
    return t


@router.post("/{task_id}/reconstruct", response_model=Task)
async def reconstruct_only(task_id: str) -> Task:
    """用已有 inpaint 数据单独重跑 reconstruct 阶段。"""
    from app.services.orchestrator import Orchestrator, schedule_reconstruct_only

    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task_manager.is_job_running(task_id):
        raise HTTPException(status_code=409, detail="任务还在运行中")

    inpaint_stage = t.stage("inpaint")
    if inpaint_stage.status not in ("completed", "skipped"):
        raise HTTPException(
            status_code=409,
            detail=f"inpaint 阶段未完成 (当前: {inpaint_stage.status})\n请先完成一次完整的 render → inpaint 流程",
        )

    # 预检重建所需资源
    orch = Orchestrator(t)
    issues = await orch._validate(start_from="reconstruct")
    if issues:
        raise HTTPException(
            status_code=400,
            detail="重建前检查未通过:\n  " + "\n  ".join(f"• {i}" for i in issues),
        )

    t.status = TaskStatus.queued
    t.error = None
    rec = t.stage("reconstruct")
    rec.status = "pending"
    rec.error = None
    await task_manager.update(t)
    schedule_reconstruct_only(t)
    return t


@router.post("/{task_id}/cancel", response_model=Task)
async def cancel_task(task_id: str) -> Task:
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task_manager.cancel_job(task_id):
        raise HTTPException(status_code=409, detail="没有正在运行的任务可取消")
    return t


@router.post("/{task_id}/views/{cam}/regenerate", response_model=Task)
async def regenerate_view_route(task_id: str, cam: str, wear_model: str | None = Query(default=None)) -> Task:
    if cam not in CAMERA_NAMES:
        raise HTTPException(status_code=400, detail=f"unknown camera: {cam}")
    t = await task_manager.get(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")

    # Only block when the orchestrator is *actually* running and in a stage
    # that conflicts (render produces the source view, reconstruct consumes
    # the wear masks). Stale status is auto-cleared by task_manager.get().
    if task_manager.is_job_running(task_id) and t.status in {
        TaskStatus.rendering,
        TaskStatus.reconstructing,
    }:
        raise HTTPException(
            status_code=409,
            detail=f"任务正在 {t.status.value} 阶段, 等它完成后再重新生成此视角",
        )

    if not t.view(cam).render_path:
        raise HTTPException(
            status_code=400,
            detail=f"{cam} 还没有渲染图, 请先完成 render 阶段",
        )

    asyncio.create_task(regenerate_view(t, cam, wear_model=wear_model))
    return t


@router.post("/{task_id}/reset", response_model=Task)
async def reset_task(task_id: str) -> Task:
    """Force a stuck task back to `failed` so it can be retried."""
    t = await task_manager.force_reset(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="任务不存在")
    return t


# ---------- file access ----------

_VALID_KINDS = {"renders", "inpaint", "textures", "debug"}


@router.get("/{task_id}/files/{kind}/{name:path}")
async def download_file(task_id: str, kind: str, name: str, inline: bool = Query(default=False)):
    if kind not in _VALID_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")
    settings = get_settings()
    safe_name = urllib.parse.unquote(name).replace("..", "")
    safe_name = safe_name.lstrip("/\\")
    target = settings.data_dir / "outputs" / task_id / kind / safe_name
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(
        str(target),
        filename=None if inline else target.name,
        media_type="image/png" if target.suffix.lower() == ".png"
                   else "model/gltf-binary" if target.suffix.lower() == ".glb"
                   else None,
    )


# ---------- WebSocket ----------

@ws_router.websocket("/ws/tasks/{task_id}")
async def task_stream(ws: WebSocket, task_id: str) -> None:
    await ws.accept()
    t = await task_manager.get(task_id)
    if not t:
        await ws.send_json({"event": "error", "detail": "任务不存在"})
        await ws.close()
        return

    queue = task_manager.subscribe(task_id)
    try:
        await ws.send_json({"event": "snapshot", "task": t.model_dump(mode="json")})
        tail = await task_manager.read_log(task_id, tail=200)
        if tail:
            for line in tail.splitlines():
                await ws.send_json({"event": "log", "line": line})
        while True:
            try:
                msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                await ws.send_json(msg)
            except asyncio.TimeoutError:
                await ws.send_json({"event": "ping"})
    except WebSocketDisconnect:
        pass
    finally:
        task_manager.unsubscribe(task_id, queue)

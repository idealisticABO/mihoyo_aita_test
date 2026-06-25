"""Pipeline orchestrator: render -> for-each view inpaint -> reconstruct.

State is mutated on the Task object and persisted via TaskManager after every
significant transition so the WebSocket subscribers see live progress.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.core.paths import safe_relative, task_output_dir
from app.core.settings_store import settings_store
from app.models.task import CAMERA_NAMES, Task, TaskStatus
from app.services.blender_runner import run_reconstruct, run_render
from app.services.comfy_client import inpaint_single_view
from app.services.task_manager import task_manager
from app.templates import TEMPLATE_DIR

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Orchestrator:
    def __init__(self, task: Task) -> None:
        self.task = task

    async def _log(self, line: str) -> None:
        await task_manager.append_log(self.task.id, line)

    async def _validate(self, start_from: str | None) -> list[str]:
        """启动前预检, 返回中文警告/错误列表。空列表 = 通过。"""
        issues: list[str] = []
        cfg = await settings_store.get()

        # 1) 模型文件
        if start_from in (None, "render"):
            model_file = self.task.model_input()
            if not model_file:
                issues.append("缺少 3D 模型文件: 请上传 .glb 或 .gltf 格式的模型")
            else:
                glb_path = get_settings().data_dir / model_file.relative_path
                if not glb_path.exists():
                    issues.append(f"模型文件不存在: {model_file.relative_path}")

        # 2) Blender
        if start_from in (None, "render", "reconstruct"):
            blender_exe = cfg.blender_executable
            if not blender_exe:
                issues.append("Blender 未配置: 请在设置页填写 Blender 可执行文件路径")
            elif not Path(blender_exe).exists():
                issues.append(f"Blender 路径无效: {blender_exe} (请检查设置)")

        # 3) ComfyUI (仅当 inpaint 启用且不是直接重建时)
        if start_from in (None, "render", "inpaint") and self.task.params.enable_inpaint:
            comfy_url = cfg.comfyui_base_url
            if not comfy_url:
                issues.append("ComfyUI 地址未配置: 请在设置页填写 ComfyUI 服务地址")

        # 4) 工作流文件
        if start_from in (None, "render", "inpaint") and self.task.params.enable_inpaint:
            from app.services.comfy_client import WEAR_MODELS, DEFAULT_WEAR_MODEL
            model_key = getattr(self.task.params, "wear_model", None) or DEFAULT_WEAR_MODEL
            if model_key in WEAR_MODELS:
                wf_path = TEMPLATE_DIR / WEAR_MODELS[model_key]["file"]
                if not wf_path.exists():
                    issues.append(f"工作流文件缺失: {WEAR_MODELS[model_key]['label']} 的 JSON 文件不存在")

        return issues

    # 常见错误 → 用户友好中文提示
    _ERROR_FRIENDLY: dict[str, str] = {
        "Blender executable not configured":
            "Blender 未配置: 请在设置页面填写 Blender 路径",
        "Command failed":
            "执行失败: Blender 或 ComfyUI 命令出错, 查看日志了解详情",
        "ComfyUI workflow failed":
            "AI 生图工作流出错: 可能是模型节点缺少 API key, 或 ComfyUI 未安装所需插件",
        "out of memory":
            "内存不足: 尝试降低渲染分辨率或关闭其他程序后重试",
        "timeout":
            "操作超时: ComfyUI 处理太慢, 可尝试换更快的生图模型或检查 GPU",
        "FileNotFoundError":
            "文件未找到: 检查上传的模型是否完整, 或 Blender 路径是否正确",
        "ConnectionError":
            "网络连接失败: ComfyUI 服务可能未启动或地址不正确",
        "no diff mask":
            "AI 差分遮罩生成失败: 工作流可能未正常输出, 查看 ComfyUI 日志",
    }

    def _friendly_error(self, raw: str) -> str:
        """原始错误 → 用户友好提示。"""
        for keyword, friendly in self._ERROR_FRIENDLY.items():
            if keyword.lower() in raw.lower():
                return friendly
        # 取第一行, 截断过长
        first_line = raw.split("\n")[0].strip()
        return f"任务失败: {first_line[:300]}"

    async def _persist(self) -> None:
        await task_manager.update(self.task)

    async def _set_stage(self, name, status, error: str | None = None) -> None:
        st = self.task.stage(name)
        st.status = status
        if status == "running":
            st.started_at = _now()
        if status in {"completed", "failed", "skipped"}:
            st.finished_at = _now()
        st.error = error

    # ------------------------------------------------------------------ stages

    async def _stage_render(self, scene_blend: Path, renders_dir: Path, script_dir: Path) -> None:
        cfg = await settings_store.get()
        model_file = self.task.model_input()
        if not model_file:
            raise RuntimeError("没有上传模型 (GLB/GLTF)")
        glb_path = get_settings().data_dir / model_file.relative_path

        self.task.status = TaskStatus.rendering
        await self._set_stage("render", "running")
        await self._persist()

        rendered = await run_render(
            cfg=cfg,
            task=self.task,
            glb_path=glb_path,
            output_dir=renders_dir,
            scene_blend_path=scene_blend,
            script_dir=script_dir,
            log=self._log,
        )

        data_dir = get_settings().data_dir
        self.task.outputs["renders"] = []
        for cam in CAMERA_NAMES:
            p = rendered.get(cam)
            if p:
                rel = safe_relative(data_dir, p)
                self.task.outputs["renders"].append(rel)
                self.task.view(cam).render_path = rel
        self.task.stage("render").outputs = list(self.task.outputs["renders"])
        await self._set_stage("render", "completed")
        await self._persist()

    async def _stage_inpaint(self, renders_dir: Path, inpaint_dir: Path) -> None:
        if not self.task.params.enable_inpaint:
            await self._set_stage("inpaint", "skipped")
            # 直接把渲染图按 wear_mask 命名拷过去, 让 reconstruct 还能跑
            inpaint_dir.mkdir(parents=True, exist_ok=True)
            import shutil

            data_dir = get_settings().data_dir
            self.task.outputs["inpaint"] = []
            for cam in CAMERA_NAMES:
                src = renders_dir / f"view_{cam}.png"
                if src.exists():
                    dst = inpaint_dir / f"view_{cam}_wear_mask.png"
                    shutil.copy2(src, dst)
                    rel = safe_relative(data_dir, dst)
                    self.task.outputs["inpaint"].append(rel)
                    v = self.task.view(cam)
                    v.inpaint_path = rel
                    v.inpaint_status = "skipped"
            await self._persist()
            return

        cfg = await settings_store.get()
        data_dir = get_settings().data_dir
        self.task.status = TaskStatus.inpainting
        await self._set_stage("inpaint", "running")
        await self._persist()

        self.task.outputs["inpaint"] = []
        idx = 0
        for cam in CAMERA_NAMES:
            idx += 1
            v = self.task.view(cam)
            render_path = renders_dir / f"view_{cam}.png"
            if not render_path.exists():
                v.inpaint_status = "skipped"
                v.error = "no render"
                continue
            v.inpaint_status = "running"
            v.started_at = _now()
            v.error = None
            await self._persist()
            await self._log(f"[inpaint] {cam}: start ({idx}/{len(CAMERA_NAMES)})")

            # 两张图之间 delay 一下, 避免 ComflyAPI 限流
            if idx > 1:
                delay = 8.0
                await self._log(f"[inpaint] delay {delay}s before {cam} ...")
                await asyncio.sleep(delay)

            last_error = None
            for attempt in range(1, 4):  # 最多 3 次
                if attempt > 1:
                    backoff = 15.0 * attempt
                    await self._log(f"[inpaint] {cam}: retry #{attempt} after {backoff}s ...")
                    await asyncio.sleep(backoff)
                try:
                    mask_path, ai_wear_path_obj = await inpaint_single_view(
                        cfg=cfg,
                        task=self.task,
                        cam_name=cam,
                        render_path=render_path,
                        output_dir=inpaint_dir,
                        log=self._log,
                    )
                    rel_mask = safe_relative(data_dir, mask_path)
                    v.inpaint_path = rel_mask
                    v.ai_wear_path = safe_relative(data_dir, ai_wear_path_obj) if ai_wear_path_obj else None
                    v.inpaint_status = "completed"
                    v.finished_at = _now()
                    self.task.outputs["inpaint"].append(rel_mask)
                    if ai_wear_path_obj:
                        rel_ai = safe_relative(data_dir, ai_wear_path_obj)
                        if rel_ai not in self.task.outputs["inpaint"]:
                            self.task.outputs["inpaint"].append(rel_ai)
                    await self._persist()
                    await self._log(f"[inpaint] {cam}: done")
                    break
                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    await self._log(f"[inpaint] {cam}: attempt {attempt} failed: {msg[:200]}")
            else:
                logger.exception("inpaint %s failed after 3 attempts", cam)
                v.inpaint_status = "failed"
                v.error = str(last_error)
                v.finished_at = _now()
                await self._persist()
                await self._log(f"[inpaint] {cam}: FAILED after 3 retries — {str(last_error)[:200]}")

        # 任一视角失败 → inpaint 整体 failed (不阻塞重建, 由用户重试)
        failed = [v for v in self.task.views if v.inpaint_status == "failed"]
        if failed:
            await self._set_stage("inpaint", "failed", error=f"{len(failed)} views failed")
        else:
            await self._set_stage("inpaint", "completed")
        self.task.stage("inpaint").outputs = list(self.task.outputs["inpaint"])
        await self._persist()

    async def _stage_reconstruct(
        self, inpaint_dir: Path, textures_dir: Path, scene_blend: Path, script_dir: Path
    ) -> None:
        cfg = await settings_store.get()
        self.task.status = TaskStatus.reconstructing
        await self._set_stage("reconstruct", "running")
        await self._persist()

        outs = await run_reconstruct(
            cfg=cfg,
            task=self.task,
            inpaint_dir=inpaint_dir,
            output_dir=textures_dir,
            scene_blend_path=scene_blend,
            script_dir=script_dir,
            log=self._log,
        )
        data_dir = get_settings().data_dir
        rels = [safe_relative(data_dir, p) for p in outs]
        self.task.outputs["textures"] = [r for r in rels if "dbg_" not in Path(r).name and not Path(r).suffix == ".glb"]
        self.task.outputs["debug"]    = [r for r in rels if "dbg_" in Path(r).name]
        self.task.outputs["glb"]      = [r for r in rels if Path(r).suffix == ".glb"]
        self.task.stage("reconstruct").outputs = self.task.outputs["textures"]
        await self._set_stage("reconstruct", "completed")
        await self._persist()

    # ------------------------------------------------------------------ run

    async def run(self, *, start_from: str | None = None) -> None:
        data_dir = get_settings().data_dir
        out_root = task_output_dir(data_dir, self.task.id)
        renders_dir = out_root / "renders"
        inpaint_dir = out_root / "inpaint"
        textures_dir = out_root / "textures"
        script_dir = out_root / "scripts"
        scene_blend = out_root / "scene.blend"

        try:
            self.task.status = TaskStatus.running
            self.task.started_at = self.task.started_at or _now()
            self.task.error = None
            await self._persist()
            await self._log(f"=== Task {self.task.id} started (resume={start_from}) ===")

            if start_from in (None, "render"):
                await self._stage_render(scene_blend, renders_dir, script_dir)

            if start_from in (None, "render", "inpaint"):
                await self._stage_inpaint(renders_dir, inpaint_dir)

                # inpaint 后暂停门: 等用户确认再重建 (防止 AI 断连导致结果不完整就重建)
                # 仅在 confirm_before_reconstruct 且不是从 reconstruct 阶段恢复时生效
                if start_from != "reconstruct" and getattr(
                    self.task.params, "confirm_before_reconstruct", True
                ):
                    self.task.status = TaskStatus.awaiting_confirm
                    await self._persist()
                    await self._log(
                        "=== inpaint 完成, 等待用户确认后再进入重建 (点击“确认重建”) ==="
                    )
                    return

            await self._stage_reconstruct(inpaint_dir, textures_dir, scene_blend, script_dir)

            self.task.status = TaskStatus.completed
            self.task.finished_at = _now()
            self.task.error = None
            await self._persist()
            await self._log("=== Task completed ===")
        except asyncio.CancelledError:
            self.task.status = TaskStatus.cancelled
            self.task.error = "Cancelled"
            self.task.finished_at = _now()
            for s in self.task.stages:
                if s.status == "running":
                    s.status = "failed"
                    s.error = "cancelled"
                    s.finished_at = _now()
            await self._persist()
            await self._log("[cancelled] task aborted by user")
            raise
        except Exception as exc:
            logger.exception("Task %s failed", self.task.id)
            raw_msg = str(exc)
            friendly = self._friendly_error(raw_msg)
            self.task.status = TaskStatus.failed
            self.task.error = friendly
            self.task.finished_at = _now()
            for s in self.task.stages:
                if s.status == "running":
                    s.status = "failed"
                    s.error = str(exc)
                    s.finished_at = _now()
            await self._persist()
            await self._log(f"[错误] {friendly}")
            await self._log(f"[原始错误] {raw_msg[:500]}")


def schedule_task(task: Task, *, start_from: str | None = None) -> asyncio.Task:
    orch = Orchestrator(task)
    job = asyncio.create_task(orch.run(start_from=start_from))
    task_manager.attach_job(task.id, job)
    return job


def schedule_reconstruct_only(task: Task) -> asyncio.Task:
    """只跑 reconstruct 阶段, 用已有的 inpaint 数据。"""
    orch = Orchestrator(task)
    job = asyncio.create_task(orch.run(start_from="reconstruct"))
    task_manager.attach_job(task.id, job)
    return job


# --------------------------------------------------------------------- single-view regenerate


async def regenerate_view(task: Task, cam: str, wear_model: str | None = None) -> Task:
    """Re-run ComfyUI inpaint for a single camera view, in-process.

    wear_model: 可传入不同生图模型 key 覆盖任务默认。
    """
    data_dir = get_settings().data_dir
    out_root = task_output_dir(data_dir, task.id)
    renders_dir = out_root / "renders"
    inpaint_dir = out_root / "inpaint"
    inpaint_dir.mkdir(parents=True, exist_ok=True)

    v = task.view(cam)
    render_path = renders_dir / f"view_{cam}.png"
    if not render_path.exists():
        raise RuntimeError(f"render 不存在: {render_path}")

    cfg = await settings_store.get()

    async def _log(line: str) -> None:
        await task_manager.append_log(task.id, line)

    v.inpaint_status = "running"
    v.started_at = _now()
    v.error = None
    await task_manager.update(task)
    await _log(f"[regenerate] {cam}: start (model={wear_model or getattr(task.params, 'wear_model', 'nano_banana')})")

    try:
        mask_path, ai_wear_path_obj = await inpaint_single_view(cfg, task, cam, render_path, inpaint_dir, _log, wear_model=wear_model)
        rel_mask = safe_relative(data_dir, mask_path)
        v.inpaint_path = rel_mask
        v.ai_wear_path = safe_relative(data_dir, ai_wear_path_obj) if ai_wear_path_obj else None
        v.inpaint_status = "completed"
        v.finished_at = _now()
        # 替换 outputs.inpaint 中的旧条目
        task.outputs["inpaint"] = [
            (rel_mask if Path(p).name == Path(rel_mask).name else p) for p in task.outputs["inpaint"]
        ]
        if rel_mask not in task.outputs["inpaint"]:
            task.outputs["inpaint"].append(rel_mask)
        if ai_wear_path_obj:
            rel_ai = safe_relative(data_dir, ai_wear_path_obj)
            task.outputs["inpaint"] = [
                (rel_ai if Path(p).name == Path(rel_ai).name else p) for p in task.outputs["inpaint"]
            ]
            if rel_ai not in task.outputs["inpaint"]:
                task.outputs["inpaint"].append(rel_ai)
        await task_manager.update(task)
        await _log(f"[regenerate] {cam}: done")
        return task
    except Exception as exc:
        logger.exception("regenerate %s failed", cam)
        raw = str(exc)
        friendly = "重新生成失败"
        for k, v in Orchestrator._ERROR_FRIENDLY.items():
            if k.lower() in raw.lower():
                friendly = v
                break
        if friendly == "重新生成失败" and raw:
            friendly = f"重新生成失败: {raw[:200]}"
        v.inpaint_status = "failed"
        v.error = friendly
        v.finished_at = _now()
        await task_manager.update(task)
        await _log(f"[regenerate] {cam}: {friendly}")
        # Fire-and-forget caller can't observe this; swallow so asyncio doesn't
        # log it as an unretrieved exception.
        return task

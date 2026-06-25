"""Image upscaler service: run SeedVR2 upscale workflow on a single render.

输入: 渲染图 + 目标分辨率 (默认 2048)
输出: 单张高清放大图
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.services.comfy_client import ComfyClient

UPSCALE_NODE_ID = "6"  # SaveImage


def load_upscale_workflow() -> dict[str, Any]:
    tpl_path = Path(__file__).resolve().parent.parent / "templates" / "upscale.json"
    return json.loads(tpl_path.read_text(encoding="utf-8"))


def inject(
    workflow: dict[str, Any],
    image_filename: str,
    resolution: int = 2048,
    seed: int = 42,
) -> dict[str, Any]:
    wf = json.loads(json.dumps(workflow))
    if "2" in wf:
        wf["2"]["inputs"]["image"] = image_filename
    if "5" in wf:
        wf["5"]["inputs"]["Number"] = str(int(resolution))
    if "1" in wf:
        wf["1"]["inputs"]["seed"] = int(seed)
    return wf


async def run_upscale(
    cfg: AppConfig,
    render_path: Path,
    output_dir: Path,
    resolution: int = 2048,
    seed: int = 42,
    log_cb=None,
) -> Path:
    """跑放大工作流,返回放大图路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    async def _log(line: str) -> None:
        if log_cb:
            await log_cb(line)

    if not render_path.exists():
        raise RuntimeError(f"render 不存在: {render_path}")

    client = ComfyClient(cfg.comfy_base_url, _log)
    if not await client.reachable():
        raise RuntimeError(f"ComfyUI 不可达: {cfg.comfy_base_url}")

    uploaded = await client.upload_image(render_path)
    await _log(f"[upscale] 上传渲染图: {uploaded}")

    workflow = load_upscale_workflow()
    workflow = inject(workflow, uploaded, resolution=resolution, seed=seed)

    await _log(f"[upscale] 启动 SeedVR2 ({resolution}px)")
    prompt_id = await client.queue_prompt(workflow)
    await _log(f"[upscale] queued prompt_id={prompt_id}")

    history = await client.wait_for(prompt_id, timeout=1800.0)

    dest = output_dir / f"upscale_{render_path.stem}.png"
    out_path = await client.download_node_output(history, UPSCALE_NODE_ID, dest)
    await _log(f"[upscale] → {out_path.name}")
    return out_path

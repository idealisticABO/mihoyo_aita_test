"""Probe local toolchain availability."""
from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

import httpx

from app.models.config import AppConfig
from app.templates import TEMPLATE_DIR

logger = logging.getLogger(__name__)

DEFAULT_WORKFLOW = TEMPLATE_DIR / "wear_default.json"


async def _probe_executable(path: str | None) -> dict:
    if not path:
        return {"ok": False, "reason": "not configured"}
    p = Path(path)
    if p.is_absolute():
        ok = p.exists()
        return {"ok": ok, "reason": None if ok else "file not found", "resolved": str(p)}
    found = shutil.which(path)
    if found:
        return {"ok": True, "resolved": found}
    return {"ok": False, "reason": "not found in PATH"}


async def _probe_file(path: str | None, hint: str, *, fallback: Path | None = None) -> dict:
    if not path:
        if fallback and fallback.exists():
            return {"ok": True, "resolved": str(fallback), "reason": "using bundled default"}
        return {"ok": False, "reason": f"{hint} not configured"}
    p = Path(path)
    ok = p.exists()
    return {"ok": ok, "reason": None if ok else "file not found", "resolved": str(p)}


async def _probe_comfy(base_url: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{base_url.rstrip('/')}/system_stats")
            return {"ok": r.status_code == 200, "status": r.status_code}
    except Exception as exc:
        return {"ok": False, "reason": str(exc)}


async def probe_all(cfg: AppConfig) -> dict:
    blender, comfy, workflow, py = await asyncio.gather(
        _probe_executable(cfg.blender_executable),
        _probe_comfy(cfg.comfyui_base_url),
        _probe_file(cfg.comfyui_workflow, "comfyui_workflow", fallback=DEFAULT_WORKFLOW),
        _probe_executable(cfg.python_executable or "python"),
    )
    return {
        "blender": blender,
        "comfyui": comfy,
        "comfyui_workflow": workflow,
        "python": py,
    }

"""Blender subprocess wrapper.

Two operations:
  * `run_render`      - inject params into render_template.py, call Blender headless.
  * `run_reconstruct` - inject params into reconstruct_template.py, open the saved
                        scene and run with -P. Reconstruction needs a 3D viewport,
                        so we DO NOT pass `-b`; uses Blender's GUI process.
"""
from __future__ import annotations

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import Awaitable, Callable

from app.models.config import AppConfig
from app.models.task import CAMERA_NAMES, Task
from app.templates import RECONSTRUCT_TEMPLATE, RENDER_TEMPLATE

logger = logging.getLogger(__name__)
LogFn = Callable[[str], Awaitable[None]]


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

async def _stream_subprocess(cmd: list[str], cwd: Path | None, log: LogFn) -> int:
    await log(f"$ {' '.join(cmd)}")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    assert proc.stdout is not None
    async for line in proc.stdout:
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            await log(text)
    rc = await proc.wait()
    await log(f"[exit code] {rc}")
    return rc


def _resolve_blender(cfg: AppConfig) -> str:
    if not cfg.blender_executable:
        raise RuntimeError("blender_executable 未配置")
    p = cfg.blender_executable
    if Path(p).is_absolute():
        return p
    found = shutil.which(p)
    if not found:
        raise RuntimeError(f"Blender executable not found: {p}")
    return found


def _render_template(values: dict[str, str | int | float | bool]) -> str:
    """Return render_template.py with placeholders substituted."""
    src = RENDER_TEMPLATE.read_text(encoding="utf-8")
    for key, val in values.items():
        token = f"__{key}__"
        if isinstance(val, str):
            replacement = val.replace("\\", "\\\\")
        else:
            replacement = repr(val) if isinstance(val, bool) else str(val)
        src = src.replace(token, replacement)
    return src


def _reconstruct_template(values: dict[str, str | int | float | bool]) -> str:
    src = RECONSTRUCT_TEMPLATE.read_text(encoding="utf-8")
    for key, val in values.items():
        token = f"__{key}__"
        if isinstance(val, str):
            replacement = val.replace("\\", "\\\\")
        else:
            replacement = repr(val) if isinstance(val, bool) else str(val)
        src = src.replace(token, replacement)
    return src


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

async def run_render(
    cfg: AppConfig,
    task: Task,
    glb_path: Path,
    output_dir: Path,
    scene_blend_path: Path,
    script_dir: Path,
    log: LogFn,
) -> dict[str, Path]:
    """Render 6 views from a GLB. Returns {cam_name: png_path}."""
    output_dir.mkdir(parents=True, exist_ok=True)
    script_dir.mkdir(parents=True, exist_ok=True)

    if not cfg.blender_executable or not Path(cfg.blender_executable).exists():
        await log("[mock] BLENDER_EXECUTABLE 未配置或缺失, 进入 mock 模式")
        return await _mock_renders(output_dir, log)

    if not glb_path.exists():
        raise RuntimeError(f"GLB 不存在: {glb_path}")

    rendered_script = script_dir / "render_runtime.py"
    rendered_script.write_text(
        _render_template(
            {
                "GLB_PATH": str(glb_path),
                "OUTPUT_DIR": str(output_dir) + ("/" if not str(output_dir).endswith(("\\", "/")) else ""),
                "SAMPLES": int(task.params.samples),
                "RENDER_RES": int(task.params.resolution),
                "CAM_DISTANCE": float(task.params.cam_distance),
                "SCENE_BLEND_PATH": str(scene_blend_path),
            }
        ),
        encoding="utf-8",
    )
    await log(f"[render] script written → {rendered_script}")

    blender = _resolve_blender(cfg)
    cmd = [blender, "-b", "-P", str(rendered_script)]
    rc = await _stream_subprocess(cmd, script_dir, log)
    if rc != 0:
        raise RuntimeError(f"Blender render exited with code {rc}")

    rendered: dict[str, Path] = {}
    for cam in CAMERA_NAMES:
        p = output_dir / f"view_{cam}.png"
        if p.exists():
            rendered[cam] = p
    if not rendered:
        raise RuntimeError("Blender finished but no view_*.png produced")
    return rendered


# ---------------------------------------------------------------------------
# Reconstruct
# ---------------------------------------------------------------------------

async def run_reconstruct(
    cfg: AppConfig,
    task: Task,
    inpaint_dir: Path,
    output_dir: Path,
    scene_blend_path: Path,
    script_dir: Path,
    log: LogFn,
) -> list[Path]:
    """Run reconstruct_template.py inside Blender against the saved scene."""
    output_dir.mkdir(parents=True, exist_ok=True)
    script_dir.mkdir(parents=True, exist_ok=True)

    if not cfg.blender_executable or not Path(cfg.blender_executable).exists():
        await log("[mock] BLENDER_EXECUTABLE 未配置, 进入 mock 模式")
        return await _mock_textures(inpaint_dir, output_dir, log)

    if not scene_blend_path.exists():
        raise RuntimeError(f"渲染场景缺失, 无法重建: {scene_blend_path}")

    rendered_script = script_dir / "reconstruct_runtime.py"
    rendered_script.write_text(
        _reconstruct_template(
            {
                "TARGET_OBJ_NAME": task.params.target_object,
                "INPUT_DIR": str(inpaint_dir) + "/",
                "OUTPUT_DIR": str(output_dir) + "/",
                "TEX_SIZE": int(task.params.tex_size),
                "INPAINT_ITERS": int(task.params.inpaint_iters),
                "SEAM_DILATE": int(getattr(task.params, 'seam_dilate', 16)),
                "WEAR_INTENSITY": int(getattr(task.params, 'wear_intensity', 50)),
                "FACING_MIN": float(task.params.facing_min),
                "OCCLUSION_REL": float(task.params.occlusion_rel),
                "SAVE_DEBUG": bool(task.params.save_debug),
                "FINAL_NAME": task.params.output_basename or task.params.final_name,
            }
        ),
        encoding="utf-8",
    )
    await log(f"[reconstruct] script written → {rendered_script}")

    blender = _resolve_blender(cfg)
    # 注意: 重建脚本依赖 3D 视口, 不能 -b
    cmd = [
        blender,
        str(scene_blend_path),
        "--python",
        str(rendered_script),
        "--python-exit-code",
        "1",
    ]
    # GUI 模式默认会卡住, 用 --background 不行 (需要视口), 这里依赖脚本结尾自己 quit
    cmd.append("--enable-autoexec")
    try:
        rc = await asyncio.wait_for(
            _stream_subprocess(cmd, script_dir, log),
            timeout=3600.0,  # 1 hour max
        )
    except asyncio.TimeoutError:
        raise RuntimeError("Reconstruction timed out after 1 hour")
    if rc not in (0, None):
        raise RuntimeError(f"Reconstruction exited with code {rc}")

    outs = sorted(p for p in output_dir.iterdir() if p.is_file())
    if not outs:
        raise RuntimeError("Reconstruction produced no files")
    return outs


# ---------------------------------------------------------------------------
# Mocks
# ---------------------------------------------------------------------------

# 1x1 transparent PNG
_TRANSPARENT_PNG = bytes.fromhex(
    "89504E470D0A1A0A0000000D49484452000000010000000108060000001F15C489"
    "0000000D49444154789C636060000000050001E5273A8E0000000049454E44AE426082"
)


async def _mock_renders(output_dir: Path, log: LogFn) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for cam in CAMERA_NAMES:
        p = output_dir / f"view_{cam}.png"
        p.write_bytes(_TRANSPARENT_PNG)
        await log(f"[mock] generated {p.name}")
        out[cam] = p
    return out


async def _mock_textures(inpaint_dir: Path, output_dir: Path, log: LogFn) -> list[Path]:
    target = output_dir / "Reconstructed_Albedo_final.png"
    src = next((p for p in sorted(inpaint_dir.iterdir()) if p.suffix.lower() in {".png", ".jpg"}), None)
    if src and src.exists():
        shutil.copy2(src, target)
    else:
        target.write_bytes(_TRANSPARENT_PNG)
    await log(f"[mock] generated {target.name}")
    return [target]

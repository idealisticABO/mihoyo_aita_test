"""Path helpers (cross-platform)."""
from __future__ import annotations

from pathlib import Path


def ensure_data_dirs(data_dir: Path) -> None:
    data_dir = Path(data_dir)
    for sub in ("uploads", "outputs", "logs"):
        (data_dir / sub).mkdir(parents=True, exist_ok=True)


def task_upload_dir(data_dir: Path, task_id: str) -> Path:
    p = Path(data_dir) / "uploads" / task_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def task_output_dir(data_dir: Path, task_id: str) -> Path:
    p = Path(data_dir) / "outputs" / task_id
    p.mkdir(parents=True, exist_ok=True)
    for stage in ("renders", "inpaint", "textures"):
        (p / stage).mkdir(exist_ok=True)
    return p


def task_log_path(data_dir: Path, task_id: str) -> Path:
    return Path(data_dir) / "logs" / f"{task_id}.log"


def safe_relative(root: Path, target: Path) -> str:
    """Return a forward-slash path relative to root if possible, else absolute."""
    try:
        return Path(target).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(target).resolve().as_posix()

"""File upload routes."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import aiofiles
from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.core.paths import safe_relative, task_upload_dir
from app.models.task import UploadedFile

logger = logging.getLogger(__name__)
router = APIRouter()

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._\-]+")


def _safe_name(name: str) -> str:
    name = name.replace("\\", "/").split("/")[-1] or "file"
    return _SAFE_NAME.sub("_", name)[:200]


@router.post("/upload", response_model=UploadedFile)
async def upload_file(
    task_id: str = Form(...),
    role: str = Form("input"),
    file: UploadFile = File(...),
) -> UploadedFile:
    if not task_id:
        raise HTTPException(status_code=400, detail="task_id required")
    settings = get_settings()
    target_dir = task_upload_dir(settings.data_dir, task_id)
    safe = _safe_name(file.filename or "file")
    dest = target_dir / safe

    size = 0
    async with aiofiles.open(dest, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            await out.write(chunk)

    return UploadedFile(
        name=safe,
        role=role,
        size=size,
        relative_path=safe_relative(settings.data_dir, dest),
    )

"""Persistent app config (writable from UI)."""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings
from app.models.config import AppConfig

logger = logging.getLogger(__name__)


class SettingsStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._cfg: AppConfig | None = None

    @property
    def path(self) -> Path:
        return get_settings().data_dir / "settings.json"

    async def load(self) -> AppConfig:
        async with self._lock:
            if self._cfg is not None:
                return self._cfg
            env = get_settings()
            base = AppConfig(
                blender_executable=env.blender_executable,
                comfyui_base_url=env.comfyui_base_url,
                comfyui_workflow=env.comfyui_workflow,
                python_executable=env.python_executable,
                output_dir=str(env.data_dir / "outputs"),
                temp_dir=str(env.data_dir / "tmp"),
            )
            if self.path.exists():
                try:
                    async with aiofiles.open(self.path, "r", encoding="utf-8") as f:
                        raw = await f.read()
                    data = json.loads(raw or "{}")
                    base = base.model_copy(update={k: v for k, v in data.items() if v is not None})
                except Exception as exc:  # pragma: no cover
                    logger.warning("Failed to load settings.json: %s", exc)
            self._cfg = base
            return base

    async def get(self) -> AppConfig:
        if self._cfg is None:
            return await self.load()
        return self._cfg

    async def update(self, patch: dict[str, Any]) -> AppConfig:
        async with self._lock:
            cur = self._cfg or await self.load()
            cleaned: dict[str, Any] = {}
            for k, v in patch.items():
                if v is None:
                    cleaned[k] = None
                elif isinstance(v, str) and v.strip() == "":
                    cleaned[k] = None
                else:
                    cleaned[k] = v
            new = cur.model_copy(update=cleaned)
            self._cfg = new
            self.path.parent.mkdir(parents=True, exist_ok=True)
            async with aiofiles.open(self.path, "w", encoding="utf-8") as f:
                await f.write(json.dumps(new.model_dump(), ensure_ascii=False, indent=2))
            return new


settings_store = SettingsStore()

"""Config routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.core.settings_store import settings_store
from app.models.config import AppConfig

router = APIRouter()


@router.get("", response_model=AppConfig)
async def get_config() -> AppConfig:
    return await settings_store.get()


@router.put("", response_model=AppConfig)
async def update_config(patch: dict[str, Any]) -> AppConfig:
    return await settings_store.update(patch)

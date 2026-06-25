"""System status routes."""
from __future__ import annotations

from fastapi import APIRouter

from app.core.settings_store import settings_store
from app.services.system_probe import probe_all

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"ok": True}


@router.get("/probe")
async def probe() -> dict:
    cfg = await settings_store.get()
    return await probe_all(cfg)

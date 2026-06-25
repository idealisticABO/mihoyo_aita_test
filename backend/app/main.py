"""FastAPI application entry."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import config as config_routes
from app.api.routes import files as files_routes
from app.api.routes import system as system_routes
from app.api.routes import tasks as tasks_routes
from app.config import get_settings
from app.core.logging import setup_logging
from app.core.paths import ensure_data_dirs
from app.core.settings_store import settings_store
from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    ensure_data_dirs(settings.data_dir)
    await settings_store.load()
    await task_manager.load()
    logger.info("Backend ready. data_dir=%s", settings.data_dir)
    yield
    await task_manager.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Blender Pipeline Studio",
        version="0.1.0",
        description="Blender → ComfyUI → Texture Reconstruction pipeline",
        lifespan=lifespan,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(system_routes.router, prefix="/api/system", tags=["system"])
    app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
    app.include_router(files_routes.router, prefix="/api/files", tags=["files"])
    app.include_router(tasks_routes.router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(tasks_routes.ws_router)
    return app


app = create_app()

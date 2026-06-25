"""FastAPI application entry."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"


class CharsetMiddleware:
    """Ensure all JSON responses include charset=utf-8."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                # Replace or add Content-Type with charset
                new_headers = []
                found_ct = False
                for k, v in headers:
                    if k == b"content-type" and b"charset" not in v:
                        new_headers.append((k, v + b"; charset=utf-8"))
                        found_ct = True
                    else:
                        new_headers.append((k, v))
                if not found_ct:
                    # No Content-Type at all (unlikely for JSON)
                    pass
                message = {**message, "headers": new_headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Blender Pipeline Studio",
        version="0.1.0",
        description="Blender → ComfyUI → Texture Reconstruction pipeline",
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
    )

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(CharsetMiddleware)

    app.include_router(system_routes.router, prefix="/api/system", tags=["system"])
    app.include_router(config_routes.router, prefix="/api/config", tags=["config"])
    app.include_router(files_routes.router, prefix="/api/files", tags=["files"])
    app.include_router(tasks_routes.router, prefix="/api/tasks", tags=["tasks"])
    app.include_router(tasks_routes.ws_router)
    return app


app = create_app()

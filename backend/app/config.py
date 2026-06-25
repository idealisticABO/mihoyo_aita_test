"""Startup configuration loaded from environment."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Backend boot settings (environment driven)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    log_level: str = Field(default="info")

    data_dir: Path = Field(default=Path("./data"))

    blender_executable: str | None = None
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_workflow: str | None = None
    python_executable: str | None = None

    cors_origins: str = "http://127.0.0.1:3000,http://localhost:3000"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir = Path(s.data_dir).resolve()
    return s

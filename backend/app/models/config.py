"""User-modifiable application config model."""
from __future__ import annotations

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    blender_executable: str | None = Field(default=None, description="Blender 可执行文件路径")
    comfyui_base_url: str = Field(default="http://127.0.0.1:8188", description="ComfyUI HTTP 地址")
    comfyui_workflow: str | None = Field(default=None, description="ComfyUI workflow JSON 路径 (留空使用内置 wear.json)")
    python_executable: str | None = Field(default=None, description="Python 可执行 (诊断用)")
    output_dir: str | None = Field(default=None, description="产物输出目录")
    temp_dir: str | None = Field(default=None, description="临时目录")

"""Task domain models."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field

# 6 个固定相机, 与 render_template.py / reconstruct_template.py 保持一致
CAMERA_NAMES: list[str] = [
    "cam_front",
    "cam_back",
    "cam_lef",
    "cam_rig",
    "cam_top",
    "cam_bott",
]


class TaskStatus(str, Enum):
    pending = "pending"
    queued = "queued"
    running = "running"
    rendering = "rendering"
    inpainting = "inpainting"
    awaiting_confirm = "awaiting_confirm"   # inpaint 完成, 等用户确认后再重建
    reconstructing = "reconstructing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


StageName = Literal["render", "inpaint", "reconstruct"]
ViewStatus = Literal["pending", "running", "completed", "failed", "skipped"]


class StageState(BaseModel):
    name: StageName
    status: Literal["pending", "running", "completed", "failed", "skipped"] = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None
    outputs: list[str] = Field(default_factory=list)


class ViewState(BaseModel):
    """Per-camera state across stages."""

    cam: str
    render_path: str | None = None             # 渲染产物 (相对 data_dir)
    inpaint_path: str | None = None            # ComfyUI 差分遮罩 (按输入图原名重命名后)
    ai_wear_path: str | None = None            # AI 生成的磨损图 (节点 21)
    inpaint_status: ViewStatus = "pending"
    prompt_id: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class TaskParams(BaseModel):
    name: str | None = None
    resolution: int = 1024                     # Blender 渲染分辨率
    samples: int = 16                          # Cycles samples
    cam_distance: float = 2.5
    enable_inpaint: bool = True
    confirm_before_reconstruct: bool = True    # inpaint 后暂停, 等用户确认再重建

    # 磨损强度控制 (方案 C: 提示词 + 后处理双轨联动)
    wear_intensity: int = 50                   # 0-100, 磨损强度
    wear_preset: str = "medium"                # light | medium | heavy | custom
    material_type: str = "metal"               # 材质类型, 影响提示词
    wear_model: str = "nano_banana"            # 生图模型: nano_banana | gpt_image | qwen_edit

    # Reconstruction
    target_object: str = "Object_2"
    tex_size: int = 1024
    inpaint_iters: int = 64
    seam_dilate: int = 16                      # UV 接缝渗色扩张像素数 (0=关闭)
    mask_denoise: str = "medium"               # 遮罩去噪: off / light / medium / strong
    facing_min: float = 0.05
    occlusion_rel: float = 0.95
    save_debug: bool = True
    final_name: str = "Reconstructed_Albedo_final"

    output_basename: str | None = None
    workflow_override: str | None = None       # 覆盖默认 workflow JSON 路径
    extra: dict[str, Any] = Field(default_factory=dict)


class UploadedFile(BaseModel):
    name: str
    role: str = "input"                        # input | model | mask | aux
    size: int = 0
    relative_path: str


class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str | None = None
    status: TaskStatus = TaskStatus.pending
    params: TaskParams = Field(default_factory=TaskParams)
    inputs: list[UploadedFile] = Field(default_factory=list)
    outputs: dict[str, list[str]] = Field(
        default_factory=lambda: {"renders": [], "inpaint": [], "textures": [], "debug": []}
    )
    views: list[ViewState] = Field(
        default_factory=lambda: [ViewState(cam=c) for c in CAMERA_NAMES]
    )
    stages: list[StageState] = Field(
        default_factory=lambda: [
            StageState(name="render"),
            StageState(name="inpaint"),
            StageState(name="reconstruct"),
        ]
    )
    error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)

    def stage(self, name: StageName) -> StageState:
        for s in self.stages:
            if s.name == name:
                return s
        raise KeyError(name)

    def view(self, cam: str) -> ViewState:
        for v in self.views:
            if v.cam == cam:
                return v
        raise KeyError(cam)

    def model_input(self) -> UploadedFile | None:
        """Return the GLB / model file uploaded by the user."""
        for f in self.inputs:
            if f.role == "model" or f.name.lower().endswith((".glb", ".gltf")):
                return f
        return None

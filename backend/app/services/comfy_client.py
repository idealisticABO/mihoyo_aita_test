"""ComfyUI client.

Per-view inpaint: for each rendered view we submit the workflow as a fresh
prompt, then download only node 51 (`wear_*`) — the AI diff mask — and rename
it `view_<cam>_wear_mask.png` so the reconstruct stage can pick it up.

If no workflow path is configured we fall back to the bundled `wear_default.json`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import shutil
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
from PIL import Image, ImageFilter

from app.models.config import AppConfig
from app.models.task import Task
from app.templates import TEMPLATE_DIR

logger = logging.getLogger(__name__)
LogFn = Callable[[str], Awaitable[None]]

# 节点 51 是 AIDiffMask 的 SaveImage; 节点 21/43 是其它存图节点
WEAR_MASK_NODE = "51"      # AIDiffMask → SaveImage
AI_WEAR_NODE = "21"        # Comfly_nano_banana2_edit → SaveImage (AI_wear_out)
DEFAULT_WORKFLOW = TEMPLATE_DIR / "wear_default.json"

# 按 _meta.title 匹配关键节点 (比节点号更稳, 不同 workflow 通用)
INPUT_IMAGE_TITLE = "渲染图输入"     # LoadImage 节点
PROMPT_TITLE = "提示词输入"          # JjkText 提示词节点

# ---------------------------------------------------------------------------
# 生图模型注册表: 每个 key 对应一个 ComfyUI workflow JSON
# 用户在 inpaint / regenerate 前选择用哪个模型
# ---------------------------------------------------------------------------
WEAR_MODELS: dict[str, dict[str, str]] = {
    "nano_banana": {
        "label": "Nano Banana (默认)",
        "file": "wear_nano_banana.json",
        "desc": "Comfly nano-banana2, 速度快, 综合效果好",
    },
    "gpt_image": {
        "label": "GPT Image",
        "file": "wear_gpt_image.json",
        "desc": "Comfly gpt-image-2, 细节丰富",
    },
    "qwen_edit": {
        "label": "Qwen Image Edit",
        "file": "wear_qwen_edit.json",
        "desc": "ModelScope Qwen-Image-Edit, 提示词自动翻译",
    },
}
DEFAULT_WEAR_MODEL = "nano_banana"


def list_wear_models() -> list[dict[str, str]]:
    """返回可选模型列表 (供前端下拉), 仅列出文件实际存在的。"""
    out: list[dict[str, str]] = []
    for key, meta in WEAR_MODELS.items():
        path = TEMPLATE_DIR / meta["file"]
        if path.exists():
            out.append({"key": key, "label": meta["label"], "desc": meta["desc"]})
    return out


def _extract_comfy_error(status: dict[str, Any]) -> str:
    """Pull a human-readable reason out of ComfyUI's status payload."""
    bits: list[str] = []
    for msg in status.get("messages") or []:
        # message format: ["event_name", {payload}]
        if isinstance(msg, list) and len(msg) == 2 and isinstance(msg[1], dict):
            payload = msg[1]
            for key in ("exception_message", "exception_type", "node_type", "node_id"):
                v = payload.get(key)
                if v:
                    bits.append(f"{key}={v}")
            traceback = payload.get("traceback")
            if isinstance(traceback, list) and traceback:
                bits.append(traceback[-1].strip())
    if not bits:
        return str(status)[:500]
    return " | ".join(bits)[:800]


# ---------------------------------------------------------------------------
# Workflow loading + injection
# ---------------------------------------------------------------------------

def load_workflow(cfg: AppConfig, task: Task, wear_model: str | None = None) -> dict[str, Any]:
    # 优先级: wear_model 参数 > TaskParams.workflow_override > TaskParams.wear_model > cfg > 默认
    model_key = wear_model or getattr(task.params, "wear_model", None) or DEFAULT_WEAR_MODEL
    override = getattr(task.params, "workflow_override", None) or cfg.comfyui_workflow
    if override:
        path = Path(override)
    elif model_key in WEAR_MODELS:
        path = TEMPLATE_DIR / WEAR_MODELS[model_key]["file"]
    else:
        path = DEFAULT_WORKFLOW
    if not path.exists():
        raise RuntimeError(f"ComfyUI workflow JSON not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def inject_input_image(workflow: dict[str, Any], image_filename: str, seed: int | None = None) -> dict[str, Any]:
    """把渲染图注入输入节点。

    匹配优先级: _meta.title == "渲染图输入" > class_type == "LoadImage"。
    同时随机化任意带 seed 的节点。
    """
    wf = json.loads(json.dumps(workflow))  # deep copy
    matched = False
    # 1) 先按 title 精确匹配
    for node_id, node in wf.items():
        if node.get("_meta", {}).get("title") == INPUT_IMAGE_TITLE and node.get("class_type") == "LoadImage":
            node.setdefault("inputs", {})["image"] = image_filename
            matched = True
    # 2) title 没命中 → 退而匹配所有 LoadImage
    for node_id, node in wf.items():
        if not matched and node.get("class_type") == "LoadImage":
            node.setdefault("inputs", {})["image"] = image_filename
        inputs = node.get("inputs", {})
        if seed is not None and "seed" in inputs and isinstance(inputs["seed"], int):
            inputs["seed"] = seed
    return wf


# ---------------------------------------------------------------------------
# Wear intensity → prompt injection
# ---------------------------------------------------------------------------

# 预设快捷映射
_WEAR_PRESETS: dict[str, int] = {"light": 20, "medium": 50, "heavy": 85}

# 材质专属基础描述
_MATERIAL_DESC: dict[str, str] = {
    "metal":   "industrial metal part with paint coating",
    "plastic":  "hard plastic component with surface coating",
    "wood":     "wooden surface with varnish or paint",
    "ceramic":  "ceramic or porcelain surface",
}

def _intensity_suffix(intensity: int) -> str:
    """0-100 → 提示词强度描述。"""
    if intensity <= 25:
        return (
            "Apply only very subtle, minimal paint chipping confined to the absolute "
            "sharpest edges and corners. Damage must be barely noticeable."
        )
    elif intensity <= 55:
        return (
            "Apply moderate, clearly visible paint peeling at transitions, raised edges, "
            "and chamfered corners. Underlying metal exposed in key contact areas."
        )
    elif intensity <= 80:
        return (
            "Apply heavy paint chipping with large continuous peeling areas along all edges, "
            "ridges, and stepped corners. Deep metal exposure with polishing marks visible."
        )
    else:
        return (
            "Apply extreme, aggressive paint chipping across all edges, ridges, and corners. "
            "Massive paint peeling, extensive bare metal exposure, pronounced wear throughout "
            "all transition zones and contact boundaries."
        )


def inject_wear_intensity(
    workflow: dict[str, Any],
    intensity: int,
    material_type: str = "metal",
) -> dict[str, Any]:
    """将磨损强度注入到 workflow 的提示词节点 (JjkText/node 25)。"""
    wf = json.loads(json.dumps(workflow))
    material_desc = _MATERIAL_DESC.get(material_type, "industrial part")
    suffix = _intensity_suffix(intensity)

    # 优先按 title "提示词输入", 退而找 JjkText 节点 (优先 node 25)
    target_id = None
    for node_id, node in wf.items():
        if node.get("_meta", {}).get("title") == PROMPT_TITLE:
            target_id = node_id
            break
    if target_id is None:
        if "25" in wf and wf["25"].get("class_type") == "JjkText":
            target_id = "25"
        else:
            for node_id, node in wf.items():
                if node.get("class_type") == "JjkText" and isinstance(
                    node.get("inputs", {}).get("text"), str
                ):
                    target_id = node_id
                    break

    if target_id is not None:
        inputs = wf[target_id].setdefault("inputs", {})
        base = str(inputs.get("text", "")).rstrip()
        inputs["text"] = f"{base}\n\nMaterial context: {material_desc}.\n{suffix}"
    return wf


def inject_prompt_text(
    workflow: dict[str, Any],
    prompt: str,
) -> dict[str, Any]:
    """直接将 LLM 生成的提示词注入到 JjkText 提示词节点。
    
    不会做任何模板拼接，LLM 给什么就用什么。
    """
    wf = json.loads(json.dumps(workflow))
    target_id = None
    for node_id, node in wf.items():
        if node.get("_meta", {}).get("title") == PROMPT_TITLE:
            target_id = node_id
            break
    if target_id is None:
        if "25" in wf and wf["25"].get("class_type") == "JjkText":
            target_id = "25"
        else:
            for node_id, node in wf.items():
                if node.get("class_type") == "JjkText" and isinstance(
                    node.get("inputs", {}).get("text"), str
                ):
                    target_id = node_id
                    break
    if target_id is not None:
        wf[target_id]["inputs"]["text"] = prompt
    return wf


# ---------------------------------------------------------------------------
# 遮罩后处理: 去除 AI 差分遮罩中的孤立噪点
# ---------------------------------------------------------------------------


def _clean_mask(mask_path: Path, *, level: str = "medium") -> Path:
    """对 ComfyUI 输出的差分遮罩做去噪, 原地覆盖保存。

    level: off / light / medium / strong
      off    — 不处理
      light  — 中值滤波 3, 开运算 3 (去孤立像素)
      medium — 中值滤波 3, 开运算 5 (去小噪点簇) ← 默认
      strong — 中值滤波 5, 开运算 7 (激进去噪, 可能丢失细节)
    """
    _LEVELS = {
        "off":    (0, 0),
        "light":  (3, 3),
        "medium": (3, 5),
        "strong": (5, 7),
    }
    median_size, opening_size = _LEVELS.get(level, _LEVELS["medium"])

    if median_size == 0:
        return mask_path
    try:
        img = Image.open(mask_path).convert("L")
    except Exception:
        return mask_path  # 打开失败则跳过

    w, h = img.size
    if w < 3 or h < 3:
        return mask_path  # 太小不处理

    # 1) 中值滤波去椒盐噪声
    if median_size >= 3:
        img = img.filter(ImageFilter.MedianFilter(size=median_size))

    # 2) 形态学开运算 = 腐蚀(去小白点) → 膨胀(恢复大区域)
    if opening_size >= 3:
        img_eroded = img.filter(ImageFilter.MinFilter(size=opening_size))
        img = img_eroded.filter(ImageFilter.MaxFilter(size=opening_size))

    # 3) 二值化 (阈值 128, 遮罩通常是黑白图)
    img = img.point(lambda x: 255 if x > 128 else 0)

    img.save(mask_path)
    logger.info("mask cleaned: %s (%dx%d level=%s)", mask_path.name, w, h, level)
    return mask_path


# HTTP client
# ---------------------------------------------------------------------------

class ComfyClient:
    def __init__(self, base_url: str, log: LogFn) -> None:
        self.base_url = base_url.rstrip("/")
        self.log = log
        self.client_id = uuid.uuid4().hex

    async def reachable(self, timeout: float = 3.0) -> bool:
        try:
            async with httpx.AsyncClient(timeout=timeout) as c:
                r = await c.get(f"{self.base_url}/system_stats")
                return r.status_code == 200
        except Exception:
            return False

    async def upload_image(self, path: Path, subfolder: str = "") -> str:
        """Upload an image to ComfyUI's input folder.

        Returns the *relative path* to pass to LoadImage (subfolder/name).
        """
        async with httpx.AsyncClient(timeout=60.0) as c:
            files = {
                "image": (path.name, path.read_bytes(), "image/png"),
                "overwrite": (None, "true"),
            }
            data = {"type": "input"}
            if subfolder:
                data["subfolder"] = subfolder
            r = await c.post(f"{self.base_url}/upload/image", files=files, data=data)
            r.raise_for_status()
            body = r.json()
            filename = body.get("name") or path.name
            # ComfyUI stores subfolder/name; LoadImage needs the full relative path
            ref = f"{subfolder}/{filename}" if subfolder else filename
            await self.log(f"[comfy] uploaded {path.name} -> {ref}")
            return ref

    async def queue_prompt(self, workflow: dict[str, Any]) -> str:
        async with httpx.AsyncClient(timeout=30.0) as c:
            r = await c.post(
                f"{self.base_url}/prompt",
                json={"prompt": workflow, "client_id": self.client_id},
            )
            body = r.json() if r.content else {}
            if r.status_code == 400:
                err_type = body.get("error", {}).get("type") if isinstance(body.get("error"), dict) else body.get("error", "")
                err_msg = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else str(body)
                raise RuntimeError(
                    f"ComfyUI rejected workflow: {err_type} — {err_msg}"
                    f" (check: workflow nodes installed? api key valid?)"
                )
            r.raise_for_status()
            prompt_id = body.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI returned no prompt_id: {body}")
            return prompt_id

    async def wait_for(self, prompt_id: str, poll_interval: float = 1.5, timeout: float = 600.0) -> dict[str, Any]:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        url = f"{self.base_url}/history/{prompt_id}"
        async with httpx.AsyncClient(timeout=15.0) as c:
            while True:
                if loop.time() > deadline:
                    raise RuntimeError(f"ComfyUI prompt {prompt_id} timeout after {timeout}s")
                try:
                    r = await c.get(url)
                    if r.status_code == 200:
                        body = r.json()
                        if prompt_id in body:
                            entry = body[prompt_id]
                            status = entry.get("status", {})
                            if status.get("status_str") == "error":
                                detail = _extract_comfy_error(status)
                                raise RuntimeError(f"ComfyUI workflow failed: {detail}")
                            # Return as soon as the prompt landed in history
                            return entry
                except httpx.HTTPError as exc:
                    await self.log(f"[comfy] poll error: {exc}")
                await asyncio.sleep(poll_interval)

    async def download_node_output(
        self, history: dict[str, Any], node_id: str, dest: Path
    ) -> Path | None:
        outputs = history.get("outputs", {})
        node_out = outputs.get(node_id)
        if not node_out:
            await self.log(f"[comfy] node {node_id} produced no output, fallback to any SaveImage")
            # fallback: pick first node with images
            for nid, no in outputs.items():
                if (no.get("images") or []):
                    node_out = no
                    node_id = nid
                    break
        if not node_out or not node_out.get("images"):
            return None
        img_info = node_out["images"][0]
        params = {
            "filename": img_info.get("filename"),
            "subfolder": img_info.get("subfolder", ""),
            "type": img_info.get("type", "output"),
        }
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.get(f"{self.base_url}/view", params=params)
            if r.status_code != 200:
                await self.log(f"[comfy] download failed {params}: {r.status_code}")
                return None
            dest.write_bytes(r.content)
            await self.log(f"[comfy] downloaded {dest.name} from node {node_id}")
            return dest


# ---------------------------------------------------------------------------
# Public API: run inpaint on one view
# ---------------------------------------------------------------------------

async def inpaint_single_view(
    cfg: AppConfig,
    task: Task,
    cam_name: str,
    render_path: Path,
    output_dir: Path,
    log: LogFn,
    wear_model: str | None = None,
) -> tuple[Path, Path | None]:
    """Run wear.json on one rendered view.

    Returns:
        (mask_path, ai_wear_path) — mask goes to reconstruct, ai_wear is for preview.
        ai_wear_path is None when node 21 produces nothing.

    Output naming:
        view_<cam>_wear_mask.png  →  reconstruct.get_view_path()  consumes this
        view_<cam>_ai_wear.png    →  frontend preview
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    mask_target = output_dir / f"view_{cam_name}_wear_mask.png"
    ai_target = output_dir / f"view_{cam_name}_ai_wear.png"

    client = ComfyClient(cfg.comfyui_base_url, log)
    if not await client.reachable():
        await log(f"[mock] ComfyUI 不可达, 直接复制渲染图为 {mask_target.name}")
        shutil.copy2(render_path, mask_target)
        shutil.copy2(render_path, ai_target)
        return mask_target, ai_target

    workflow = load_workflow(cfg, task, wear_model=wear_model)
    resolved_model = wear_model or getattr(task.params, "wear_model", None) or DEFAULT_WEAR_MODEL
    await log(f"[comfy] {cam_name}: using wear_model={resolved_model}")
    # 上传渲染图 → ComfyUI input 目录
    load_ref = await client.upload_image(render_path, subfolder=f"task_{task.id}")
    workflow = inject_input_image(workflow, load_ref, seed=random.randint(1, 2**31 - 1))

    # 方案 C: 将 wear_intensity + material_type 注入提示词
    intensity = getattr(task.params, "wear_intensity", 50)
    preset = getattr(task.params, "wear_preset", "medium")
    if preset in _WEAR_PRESETS and preset != "custom":
        intensity = _WEAR_PRESETS[preset]
    material = getattr(task.params, "material_type", "metal")

    # ---- LLM 看图生成提示词 (优先) ----
    from app.services.llm_prompt import generate_wear_prompt
    render_path = output_dir.parent / "renders" / f"view_{cam_name}.png"
    try:
        wp = await generate_wear_prompt(
            render_path,
            material_type=material,
            wear_intensity=intensity,
            log_cb=_log,
        )
        # 立即解包为 str, 避免 WearPrompt dataclass 跨 await 被序列化
        llm_positive = wp.positive
        llm_negative = wp.negative
        llm_thought = wp.thought
        llm_obj_id = wp.object_id

        if llm_positive:
            full_prompt = llm_positive
            if llm_negative:
                full_prompt += f"\n\nAvoid: {llm_negative}"
            workflow = inject_prompt_text(workflow, full_prompt)
            await log(f"[comfy] {cam_name}: LLM prompt ok ({len(llm_positive)} chars) object={llm_obj_id}")
        else:
            raise RuntimeError("LLM returned empty prompt")
    except Exception as llm_err:
        await log(f"[comfy] {cam_name}: LLM prompt failed ({llm_err}), fallback to template")
        workflow = inject_wear_intensity(workflow, intensity=intensity, material_type=material)

    await log(f"[comfy] {cam_name}: wear_intensity={intensity} preset={preset} material={material}")

    prompt_id = await client.queue_prompt(workflow)
    await log(f"[comfy] {cam_name} queued prompt_id={prompt_id}")

    # 把 prompt_id 写回 task.view
    try:
        task.view(cam_name).prompt_id = prompt_id
    except KeyError:
        pass

    history = await client.wait_for(prompt_id)

    # 下载两个输出: 差分遮罩 (重构用) + AI 磨损图 (预览用)
    out_mask = await client.download_node_output(history, WEAR_MASK_NODE, mask_target)
    if not out_mask:
        raise RuntimeError(f"ComfyUI returned no diff mask for {cam_name}")

    # 遮罩后处理: 去除孤立噪点
    denoise = getattr(task.params, "mask_denoise", "medium")
    _clean_mask(out_mask, level=denoise)

    out_ai = await client.download_node_output(history, AI_WEAR_NODE, ai_target)
    if out_ai:
        await log(f"[comfy] {cam_name}: AI wear image saved")
    else:
        await log(f"[comfy] {cam_name}: no AI wear image from node {AI_WEAR_NODE}")

    return out_mask, out_ai

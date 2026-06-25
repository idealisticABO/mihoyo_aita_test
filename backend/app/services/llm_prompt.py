"""LLM 驱动磨损提示词生成器 (v2)。

在 inpaint 前调用，传渲染图 + 材质 + 磨损强度 → LLM 分析图像几何结构、
推演物理磨损逻辑 → 返回结构化提示词 (positive/negative + 分析日志)。
"""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---- System Prompt (v2: 资深3D材质纹理艺术家) ----
SYSTEM_PROMPT = r"""# Role: 资深3D材质纹理艺术家 & ComfyUI 提示词工程专家

## Objective:
你的任务是精准识别用户上传的干净渲染图（或产品图），并根据用户指定的【材质类别】和【磨损强度】，推演出符合物理逻辑的磨损细节，最终生成用于 ComfyUI (Stable Diffusion) 的高质量中英文提示词。

## Input Variables (用户将提供):
1. [图片]: 干净的3D渲染图或产品图。
2. [材质类别]: 例如：金属(Metal)、塑料(Plastic)、木头(Wood)、皮革(Leather)、织物(Fabric)等。
3. [磨损强度]: 轻度(Light)、中度(Medium)、重度(Heavy)、战损(Battle-damaged)。

## Workflow (执行逻辑):

### Step 1: 图像几何与功能分析 (Object Analysis)
- 识别图片中的主体是什么（例如：机械臂、头盔、相机、沙发）。
- 拆解物体的几何特征与功能区域，分为：
  - **边缘/转角 (Edges/Corners)**：最容易发生碰撞、掉漆和刮擦的地方。
  - **接触面/抓握区 (Contact/Grip areas)**：最容易产生油污、抛光、指纹或材质剥落的地方。
  - **缝隙/凹陷处 (Crevices/Cavities)**：最容易积灰、生锈、藏污纳垢的地方。
  - **大块平整表面 (Flat Surfaces)**：通常只有随机的细微划痕或轻微褪色。

### Step 2: 物理磨损逻辑推演 (Wear & Tear Logic)
结合【材质类别】和【磨损强度】，生成精确的磨损描述：
- **金属 (Metal)**: 边缘掉漆露出底漆或亮银色金属、表面氧化/生锈(Rust)、油污、深浅不一的划痕、金属凹陷(Dents)。
- **塑料 (Plastic)**: 边缘磨圆/发白(Stress whitening)、表面划痕、油光发亮(手汗长期摩擦)、老化发黄(Yellowing)、微小裂纹。
- **皮革/布料**: 边缘磨损起毛、开裂、褪色、污渍沉淀、失去光泽。
- *强度控制*：
  - 轻度：仅边缘微小掉漆/划痕，缝隙少许灰尘。
  - 中度：明显的经常使用痕迹，大面积轻微划痕，把手处明显磨损。
  - 重度/战损：结构性破坏，严重锈蚀/裂纹，大块涂层剥落，严重污垢。

### Step 3: ComfyUI 提示词生成 (Prompt Generation)
将推演结果转化为 Stable Diffusion 容易理解的提示词（Danbooru标签法与自然语言结合）。
- **要求精准定位**：必须使用方位词（如 `on the edges`, `around the joints`, `in the crevices`, `on the top surface`）。
- **画质增强词**：自动加入 `8k resolution, highly detailed, photorealistic, PBR texture, octane render, macro photography, 8k UHD` 等提升质感的词汇。

## Output Format (必须严格输出此 JSON 格式):
```json
{
  "thought_process": "简要描述你对该物体的结构分析，以及为何在这个位置添加这种磨损（中文，限100字以内，用于日志记录和逻辑自洽）。",
  "object_identifier": "用简短的英文词组描述主体是什么，例如 a sci-fi mechanical helmet",
  "comfyui_positive_prompt": "主体英文描述 + 环境光影词汇 + 精确的部位磨损英文提示词 + 材质纹理强化词汇。(用逗号分隔，按重要程度排序)",
  "comfyui_negative_prompt": "低质量、模糊、卡通、干净无瑕、不合理结构等反向提示词。"
}
```"""

# ---- API 配置 ----
DEFAULT_BASE_URL = "https://api.siliconflow.cn/v1/chat/completions"
DEFAULT_MODEL = "Pro/moonshotai/Kimi-K2.6"
DEFAULT_API_KEY = "sk-lklzsqxwozgbqktstdniwtnmeummflkzckjbklwyucuhigqp"
TIMEOUT = 120.0  # 图片 + JSON 输出, 给足时间


# ---- 返回结构 ----
@dataclass
class WearPrompt:
    """LLM 生成的完整磨损提示词组。"""
    positive: str = ""            # comfyui_positive_prompt
    negative: str = ""            # comfyui_negative_prompt
    thought: str = ""             # thought_process (中文日志)
    object_id: str = ""           # object_identifier
    meta: dict[str, Any] = field(default_factory=dict)  # 原始 JSON

    def to_dict(self) -> dict[str, Any]:
        return {
            "positive": self.positive,
            "negative": self.negative,
            "thought": self.thought,
            "object_id": self.object_id,
            "meta": self.meta,
        }

    def __getstate__(self) -> dict:
        return self.to_dict()


def _intensity_label(intensity: int) -> str:
    """0-100 → Chinese label matching system prompt."""
    if intensity <= 20:
        return "轻度 (Light)"
    elif intensity <= 55:
        return "中度 (Medium)"
    elif intensity <= 80:
        return "重度 (Heavy)"
    return "战损 (Battle-damaged)"


def _material_cn(material: str) -> str:
    """材质 key → Chinese label."""
    return {
        "metal": "金属 (Metal)",
        "plastic": "塑料 (Plastic)",
        "wood": "木头 (Wood)",
        "leather": "皮革 (Leather)",
        "fabric": "织物 (Fabric)",
        "ceramic": "陶瓷 (Ceramic)",
        "glass": "玻璃 (Glass)",
    }.get(material, material)


def _extract_json(text: str) -> dict | None:
    """从 LLM 输出中提取 JSON，容忍 markdown 代码块包裹。"""
    # 优先找 ```json ... ``` 块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 直接从文本中找最外层 { ... }
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return None


async def generate_wear_prompt(
    image_path: Path,
    material_type: str = "metal",
    wear_intensity: int = 50,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    log_cb=None,
) -> WearPrompt:
    """调 LLM 分析渲染图 → 返回结构化磨损提示词。

    Returns:
        WearPrompt with positive/negative prompts + thought log.
        如果 LLM 完全失败, 返回空 WearPrompt (positive="" 表示需回退)。
    """
    empty = WearPrompt()

    if not image_path.exists():
        logger.warning("render image not found: %s, skip LLM", image_path)
        return empty

    image_b64 = base64.b64encode(image_path.read_bytes()).decode()

    mat_label = _material_cn(material_type)
    level_label = _intensity_label(wear_intensity)

    user_prompt = (
        f"请分析这张渲染图并生成磨损提示词。\n"
        f"材质类别: {mat_label}\n"
        f"磨损强度: {level_label}"
    )

    payload: dict[str, Any] = {
        "model": model or DEFAULT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                    },
                ],
            },
        ],
        "temperature": 0.7,
        "max_tokens": 1920,
        "stream": False,
    }

    key = api_key or DEFAULT_API_KEY
    url = base_url or DEFAULT_BASE_URL

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.exception("LLM API call failed: %s", exc)
        return empty

    raw = data["choices"][0]["message"]["content"].strip()
    parsed = _extract_json(raw)

    if parsed is None:
        logger.warning("LLM 输出非 JSON, 回退模板。raw=%s", raw[:200])
        return empty

    positive = str(parsed.get("comfyui_positive_prompt", "")).strip()
    if not positive:
        logger.warning("LLM JSON 缺 positive_prompt")
        return empty

    result = WearPrompt(
        positive=positive,
        negative=str(parsed.get("comfyui_negative_prompt", "")).strip(),
        thought=str(parsed.get("thought_process", "")).strip(),
        object_id=str(parsed.get("object_identifier", "")).strip(),
        meta=parsed,
    )

    if log_cb:
        await log_cb(f"[LLM] {image_path.name}: {result.thought}")

    logger.info(
        "LLM prompt generated: object=%s positive=%d chars negative=%d chars",
        result.object_id, len(result.positive), len(result.negative),
    )
    return result

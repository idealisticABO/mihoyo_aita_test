"""Background-removal service: run the 3-method remove_bg.json workflow.

输入: 渲染图 + 可选 prompt (用于 SAM+DINO)
输出: 三张去背景结果 (inspyrenet / bria / sam)
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import AppConfig
from app.services.comfy_client import ComfyClient

METHODS = ["inspyrenet", "bria", "sam"]

# 节点 ID 对应每种方法的 SaveImage
METHOD_NODE_ID = {
    "inspyrenet": "100",
    "bria": "101",
    "sam": "102",
}


def load_remove_bg_workflow() -> dict[str, Any]:
    """加载 remove_bg.json 模板。"""
    tpl_path = Path(__file__).resolve().parent.parent / "templates" / "remove_bg.json"
    return json.loads(tpl_path.read_text(encoding="utf-8"))


def inject_input(workflow: dict[str, Any], image_filename: str, prompt: str) -> dict[str, Any]:
    """注入输入图文件名和 SAM prompt。"""
    wf = json.loads(json.dumps(workflow))
    # 节点 2 是 LoadImage
    if "2" in wf:
        wf["2"]["inputs"]["image"] = image_filename
    # 节点 43 是 prompt 字符串
    if "43" in wf:
        wf["43"]["inputs"]["String"] = prompt or "foreground object"
    return wf


def select_methods(workflow: dict[str, Any], methods: list[str]) -> dict[str, Any]:
    """只保留用户选中的方法分支,删除其它 SaveImage 节点,
    避免缺失节点时整个工作流失败。
    """
    wf = json.loads(json.dumps(workflow))
    for m in METHODS:
        if m not in methods:
            node_id = METHOD_NODE_ID[m]
            wf.pop(node_id, None)
    return wf


async def run_remove_bg(
    cfg: AppConfig,
    render_path: Path,
    output_dir: Path,
    prompt: str,
    methods: list[str] | None = None,
    log_cb=None,
) -> dict[str, Path]:
    """跑去背景工作流,返回 {method_key: 输出 PNG 路径}。

    Args:
        cfg: AppConfig (含 comfy_base_url)
        render_path: 输入渲染图
        output_dir: 结果保存目录
        prompt: SAM+DINO 用的中文 prompt (会经混元翻译)
        methods: 要跑哪些方法,默认全跑
        log_cb: 日志回调
    """
    if methods is None:
        methods = list(METHODS)
    output_dir.mkdir(parents=True, exist_ok=True)

    async def _log(line: str) -> None:
        if log_cb:
            await log_cb(line)

    if not render_path.exists():
        raise RuntimeError(f"render 不存在: {render_path}")

    client = ComfyClient(cfg.comfy_base_url, _log)
    if not await client.reachable():
        raise RuntimeError(f"ComfyUI 不可达: {cfg.comfy_base_url}")

    # 上传输入图
    uploaded = await client.upload_image(render_path)
    await _log(f"[rmbg] 上传渲染图: {uploaded}")

    # 构造工作流
    workflow = load_remove_bg_workflow()
    workflow = select_methods(workflow, methods)
    workflow = inject_input(workflow, uploaded, prompt)

    await _log(f"[rmbg] 启动工作流, 方法={methods}, prompt='{prompt}'")
    prompt_id = await client.queue_prompt(workflow)
    await _log(f"[rmbg] queued prompt_id={prompt_id}")

    history = await client.wait_for(prompt_id, timeout=900.0)

    # 收集结果
    results: dict[str, Path] = {}
    for m in methods:
        node_id = METHOD_NODE_ID[m]
        dest = output_dir / f"bg_{m}_{render_path.stem}.png"
        try:
            out_path = await client.download_node_output(history, node_id, dest)
            results[m] = out_path
            await _log(f"[rmbg] {m} → {out_path.name}")
        except Exception as e:
            await _log(f"[rmbg] ⚠ {m} 失败: {e}")
    return results

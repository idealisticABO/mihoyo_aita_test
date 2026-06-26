# AI 模型磨损纹理生成工具 (Blender Pipeline Studio)

基于 Blender + ComfyUI + 多AI生图模型的 3D 模型磨损纹理自动生成工具。

**支持流程**: 输入无磨损模型(GLB/GLTF) → 多视角渲染 → AI生图(多模型可选) → 差分遮罩生成 + 去噪 → 投影烘焙回UV → 贴图合成 + UV接缝处理 → 导出带贴图GLB → 网页3D预览

---

## 架构

```
┌─────────────┐     ┌──────────────┐          ┌──────────────┐
│  Next.js 前端 │────▶│  FastAPI 后端  │────▶│  Blender CLI  │  渲染 / 重建
│  :3000       │◀────│  :8000        │◀──── │ (场景.blend)  │
│              │     │  orchestrator │        └──────────────┘
│  3D预览      │     │  + WebSocket  │     ┌──────────────┐
│  (three.js)  │     │              │────▶│  ComfyUI API  │  AI生图
└─────────────┘     └──────────────┘     │  :8188        │
                                         └──────────────┘
```

- **前端**: Next.js 14 (App Router) + Tailwind + react-three-fiber (3D预览)
- **后端**: FastAPI + asyncio orchestrator, JSON持久化, WebSocket实时推送
- **存储**: 全部本地 `data/` 目录, 无外部数据库依赖

---

## 快速开始

### 1. 后端

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
copy .env.example .env          # Windows
# cp .env.example .env          # macOS / Linux
python run.py
```

默认监听 `http://127.0.0.1:8000`。Swagger UI: `http://127.0.0.1:8000/docs`。

> 所有 JSON 响应强制带 `charset=utf-8`，确保中文显示正常。

### 2. 前端

```bash
cd frontend
npm install
npm run dev
```

默认监听 `http://127.0.0.1:3000`。

### 3. 首次配置

打开 `http://127.0.0.1:3000/config`, 填入:
- **Blender 可执行文件路径** — 例 `C:\Program Files\Blender Foundation\Blender 4.2\blender.exe`
- **`.blend` 场景路径** — 含6个相机(`cam_front/back/lef/rig/top/bott`)和目标对象的场景
- **ComfyUI 地址** — 默认 `http://127.0.0.1:8188`
- **输出目录** — 所有产物存这里

---

## 核心功能

### 工作流阶段

| 阶段 | 状态值 | 说明 |
|---|---|---|
| **render** | `rendering` | Blender 6视角渲染(前/后/左/右/上/下), 每视角 1024² png |
| **inpaint** | `inpainting` | ComfyUI 逐个视角 AI 生图 → 差分遮罩提取 → 遮罩后处理(去噪) |
| *暂停门* | `awaiting_confirm` | inpaint 完成后自动暂停, 等待人工确认结果 |
| **reconstruct** | `reconstructing` | 6视角遮罩投影烘焙→合成→UV接缝处理→贴图导出→GLB导出 |
| **完成** | `completed` | 可下载贴图 + 3D预览GLB |

### 多生图模型切换

新建任务页选择, 三个 ComfyUI 工作流接口节点一致(按 `_meta.title` 匹配), 切换零代码:

| 模型 | key | 说明 |
|---|---|---|
| **Nano Banana (DMU)** | `nano_banana` | 默认, 均衡速度与质量 |
| **GPT Image-2** | `gpt_image` | OpenAI 高精度生图 |
| **Qwen Image Edit** | `qwen_edit` | ModelScope 编辑模型, 内置翻译 |

> 扩展: 往 `backend/app/templates/` 放新工作流 JSON, 在 `comfy_client.py` 的 `WEAR_MODELS` 注册一行即可。接口节点号(4/25/21/51)保持一致。

### 磨损强度控制 (双轨方案)

| 轨道 | 作用 | 实现位置 |
|---|---|---|
| **AI层**(提示词注入) | 调整 ComfyUI JjkText 节点提示词: 轻→中→重的磨损描述后缀 | `inject_wear_intensity()` |
| **确定性层**(后处理) | 二值化阈值 + 形态学膨胀, 控制遮罩覆盖面积 | `apply_wear_intensity()` (Blender重建脚本内) |

新建任务页提供:
- **预设按钮**: 轻微(20) / 中等(50) / 严重(85)
- **0-100 slider** 精细调整
- **材质下拉**: 金属(metal) / 塑料(plastic) → 不同材质提示词策略

### UV 接缝处理

| 手段 | 参数 | 说明 |
|---|---|---|
| **烘焙边缘扩展** | `bake.margin=16` | 烘焙时在UV岛边缘多采样16px, 防止岛间断裂 |
| **渗色扩张** | `SEAM_DILATE=16` (可调) | 合成后把有色像素向邻域"渗血", 填充UV边界空隙 |

```python
# reconstruct_template.py
def dilate_seam(arr, margin=8):
    """把非透明像素向四周扩张 margin 像素, 填补 UV 岛之间的缝隙。"""
    # 迭代膨胀: 每次把有颜色→空白的邻域像素复制过来
```

新建任务页 `UV接缝渗色(px)` 参数可调, 设 0 则关闭。

### 遮罩去噪

ComfyUI 输出的差分遮罩常有椒盐噪声(孤立黑白点)。在 `inpaint_single_view` 下载遮罩后自动执行去噪:

| 级别 | 中值滤波核 | 开运算核 | 适用场景 |
|---|---|---|---|
| `off` | — | — | 不处理 |
| `light` | 3×3 | 3×3 | 去孤立像素, 保留细节 |
| **`medium`(默认)** | 3×3 | 5×5 | 去小噪点簇, 推荐 |
| `strong` | 5×5 | 7×7 | 激进去噪, 可能丢失细微磨损 |

```python
# comfy_client.py
def _clean_mask(mask_path, level="medium"):
    img = Image.open(mask_path).convert("L")
    img = img.filter(ImageFilter.MedianFilter(size=3))  # 去椒盐
    img = img.filter(ImageFilter.MinFilter(size=5))      # 腐蚀(去白噪)
    img = img.filter(ImageFilter.MaxFilter(size=5))      # 膨胀(恢复大区域)
    img.point(lambda x: 255 if x > 128 else 0).save(mask_path)  # 二值化
```

### 确认门 (awaiting_confirm)

inpaint 完成后**不会自动进入 reconstruct**。任务状态变为 `awaiting_confirm`:

- 检查各视角 inpaint 结果
- 不满意某视角 → 六视角区切换模型后点 **"重新生成 inpaint"**
- 确认无误 → 点 **✓ 确认重建** (绿色按钮)
- 重建完成后 → 点 **🔄 重新重建** 可用不同参数重新贴图 (不重跑 render/inpaint)

### API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/tasks` | 列出所有任务 |
| POST | `/api/tasks` | 创建任务 |
| GET | `/api/tasks/{id}` | 获取单个任务 |
| **PATCH** | `/api/tasks/{id}` | **任务重命名 `{"name": ...}`** |
| **DELETE** | `/api/tasks/{id}` | **删除任务 (保留磁盘文件)** |
| POST | `/api/tasks/{id}/run` | 运行任务 |
| POST | `/api/tasks/{id}/retry` | 重试失败任务 |
| POST | `/api/tasks/{id}/cancel` | 取消运行中任务 |
| POST | `/api/tasks/{id}/continue` | 确认重建 (awaiting_confirm → reconstruct) |
| POST | `/api/tasks/{id}/reconstruct` | 重新重建 (跳过 render/inpaint) |
| POST | `/api/tasks/{id}/reset` | 强制重置为 failed |
| POST | `/api/tasks/{id}/views/{cam}/regenerate` | 单视角重新 inpaint |
| **POST** | `/api/tasks/{id}/views/{cam}/remove-bg` | **去背景执行** |
| **POST** | `/api/tasks/{id}/views/{cam}/select-bg` | **选择去背景结果** |
| **POST** | `/api/tasks/{id}/views/{cam}/upscale` | **高清放大** |
| **POST** | `/api/tasks/{id}/views/{cam}/use-upscale` | **启用/关闭放大图** |
| POST | `/api/tasks/{id}/views/{cam}/reset` | 重置视角 inpaint 状态 |
| GET | `/api/tasks/{id}/files/{kind}/{name}` | 下载文件 |
| GET | `/api/tasks/{id}/logs` | 获取日志 |
| WS | `/api/tasks/{id}/ws` | WebSocket 实时推送 |

### 3D 模型预览

completed 状态且重建完成(有GLB)时, 点击 **🧊 3D 预览**:
- react-three-fiber 渲染器, 支持鼠标旋转/缩放/平移
- 环境光 + 网格地面, 直观查看磨损贴图效果
- 可下载 GLB 文件

### 背景去除 (Remove BG)

inpaint 阶段可选使用去背景图替代原渲染图作为输入，默认不开启:

| 方法 | 特点 |
|------|------|
| **InspyrenetRembg** | 速度快，清晰前景效果好 |
| **BRIA RMBG** | 边缘细节好(发丝/网格) |
| **SAM + GroundingDINO** | 文本驱动，精确但慢，需 prompt |

**使用流程**:
1. 渲染完成后，在视角卡片点 ✂ 去背景
2. 弹窗输入 prompt → 勾选方法 → 点 ▶ 运行
3. 后台跑 ComfyUI，WebSocket 推送结果
4. 点击选中一张候选图
5. 点重新生成 inpaint → 用所选去背景图作为输入

### 高清放大 (Upscale)

基于 SeedVR2 视频超分模型对渲染图进行超分（默认 2048px），默认不启用:

| 参数 | 说明 |
|------|------|
| DiT 模型 | `seedvr2_ema_3b_fp8_e4m3fn.safetensors` |
| VAE 模型 | `ema_vae_fp16.safetensors` |
| 默认分辨率 | 2048px |

**使用流程**:
1. 渲染完成后，在视角卡片点 🔍 放大
2. 后台跑超分，完成后标记
3. 点「启用放大图作为 inpaint 输入」
4. 点重新生成 inpaint → 用放大图作为输入

**输入优先级**: `去背景图 > 放大图 > 原渲染图`

### UV 健康检查 (自动修复)

`ensure_uvs()` 在展开 UV 前自动执行完整健康检查:

| 检查项 | 检测方式 | 触发修复 |
|--------|----------|----------|
| **无 UV** | `mesh.uv_layers` 为空 | Smart UV 自动展开 |
| **UV 超范围 (重复/tiling)** | 采集 UV 坐标 min/max，超出 ±0.01 | 重新 Smart UV 展开 |
| **UV 反向 (镜像)** | 三角面 UV winding cross product，统计翻转比例 | 混合镜像(10-90%)时重新展开 |

### 任务管理

| 功能 | 位置 | 操作 |
|------|------|------|
| **重命名** | 任务列表 / 详情页标题 | 点击名称，内联编辑，Enter 保存 |
| **删除** | 任务列表 (悬停显示) | 点删除 → 二次确认「确认/取消」 |

### 详情页按钮逻辑

每个任务状态只显示有意义的操作:

| 状态 | 显示的按钮 |
|------|----------|
| `pending / queued` | ▶ 启动 |
| `running / rendering / inpainting / reconstructing` | ✕ 取消 |
| `awaiting_confirm` | ✓ 确认重建 |
| `completed` | 🧊 3D预览 + 🔄 重新重建 |
| `failed` | 🔁 重试 + 🔄 重新重建(如有inpaint) |

### 启动前校验

点启动时三层检查:
1. **前端**: 模型是否上传 / 任务名是否填写
2. **后端API**: 模型文件存在 / Blender已配置 / ComfyUI已配置 / 工作流JSON存在
3. **运行时**: 错误自动翻译为中文友好提示 (如"Blender路径无效"代替原始 Python 堆栈)

---

## 目录约定

```
data/
├── settings.json                  # 前端配置页保存的设置
├── tasks.json                     # 任务索引
├── uploads/<task_id>/             # 用户上传的 GLB/GLTF 模型
├── outputs/<task_id>/
│   ├── renders/                   # Blender 6视角渲染 (view_cam_*.png)
│   ├── inpaint/                   # ComfyUI 差分遮罩 (view_*_wear_mask.png)
│   ├── bg_removed/                # 去背景结果 (bg_<method>_*.png)
│   ├── upscaled/                  # 高清放大 (upscale_*.png)
│   ├── textures/                  # 最终贴图 + GLB
│   │   ├── Reconstructed_Albedo_final.png
│   │   ├── Reconstructed_Albedo_final.glb   # 带贴图的3D模型
│   │   └── dbg_*.png              # 调试图 (if save_debug=true)
│   └── scripts/                   # 运行时生成的 Blender 脚本
└── logs/<task_id>.log
```

---

## 扩展指南

### 添加新AI生图模型

1. 从 ComfyUI 导出 API 格式的 workflow JSON
2. 放到 `backend/app/templates/wear_<name>.json`
3. 在 `backend/app/services/comfy_client.py` 的 `WEAR_MODELS` 注册:
   ```python
   "my_model": {"file": "wear_my_model.json", "label": "我的模型", "desc": "..."}
   ```
4. 确保接口节点有 `_meta.title` = `"渲染图输入"` / `"提示词输入"` (或节点号 4/25)
5. 新建任务页自动显示为新卡片

### 添加新材质

在 `_MATERIAL_DESC` 字典添加键值对, 前端材质下拉自动同步:
```python
_MATERIAL_DESC: dict[str, str] = {
    "metal":   "industrial metal part...",
    "plastic": "hard plastic component...",
    "wood":    "weathered wooden surface...",   # 新增
}
```

### 自定义参数

`TaskParams` (Pydantic model) 定义所有可调参数:
- `backend/app/models/task.py` — 加字段
- `frontend/lib/types.ts` — 同步类型
- `frontend/app/tasks/new/page.tsx` — 加 UI 控件
- 如 Blender 重建阶段需要, 同步到 `_reconstruct_template()` 的参数注入字典

### Mock 模式

任何外部工具路径未配置时, 对应步骤进入 mock 模式:
- Blender 未配置 → render 阶段生成占位 1×1 透明 PNG
- ComfyUI 未配置 → inpaint 阶段复制渲染图为遮罩
- 方便先打通前后端, 再逐步接入实际工具

---

## License

MIT

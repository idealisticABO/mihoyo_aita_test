# Blender / Reconstruct 脚本模板

后端在执行任务时, 会把这两个模板复制到任务目录, 用占位符替换头部的常量, 再调用 Blender 执行。

## 占位符约定 (后端 services/blender_runner.py / reconstruct_runner.py)

### `render_template.py`
- `__GLB_PATH__`         → 用户上传的 GLB 文件绝对路径
- `__OUTPUT_DIR__`       → 渲染输出目录 (绝对路径, 末尾 `/`)
- `__SAMPLES__`          → Cycles 采样数 (int)
- `__RENDER_RES__`       → 渲染分辨率 (int)
- `__CAM_DISTANCE__`     → 相机距离 (float)
- `__SCENE_BLEND_PATH__` → 渲染完成后保存的 .blend 路径

### `reconstruct_template.py`
- `__TARGET_OBJ_NAME__`  → mesh 名称 (默认 `Object_2`)
- `__INPUT_DIR__`        → ComfyUI inpaint 输出目录
- `__OUTPUT_DIR__`       → 贴图输出目录
- `__TEX_SIZE__`         → 贴图分辨率
- `__INPAINT_ITERS__`    → inpaint 迭代次数
- `__FACING_MIN__`       → 朝向阈值
- `__OCCLUSION_REL__`    → 遮挡阈值
- `__SAVE_DEBUG__`       → True / False
- `__FINAL_NAME__`       → 最终贴图基名 (默认 `Reconstructed_Albedo_final`)

模板源自用户提供的 `render.py` 与 `reconstruct_texture.py`, 保持原算法不变, 只替换顶部配置常量。

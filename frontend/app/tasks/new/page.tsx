"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { TaskParams, UploadedFile } from "@/lib/types";

const DEFAULTS: TaskParams = {
  name: "",
  resolution: 1024,
  samples: 16,
  cam_distance: 2.5,
  enable_inpaint: true,
  confirm_before_reconstruct: true,
  wear_intensity: 50,
  wear_preset: "medium",
  material_type: "metal",
  wear_model: "nano_banana",
  target_object: "Object_2",
  tex_size: 1024,
  inpaint_iters: 64,
  seam_dilate: 16,
  mask_denoise: "medium",
  facing_min: 0.05,
  occlusion_rel: 0.95,
  save_debug: true,
  final_name: "Reconstructed_Albedo_final",
  output_basename: "",
  workflow_override: "",
};

export default function NewTaskPage() {
  const router = useRouter();
  const [params, setParams] = useState<TaskParams>(DEFAULTS);
  const [model, setModel] = useState<UploadedFile | null>(null);
  const [extras, setExtras] = useState<UploadedFile[]>([]);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wearModels, setWearModels] = useState<{ key: string; label: string; desc: string }[]>([]);

  useEffect(() => {
    api.getWorkflowModels().then((r) => setWearModels(r.items)).catch(() => {});
  }, []);

  const ensureTask = async () => {
    if (taskId) return taskId;
    const t = await api.createTask({ name: params.name || null, params });
    setTaskId(t.id);
    return t.id;
  };

  const onModel = async (f: File | null) => {
    if (!f) return;
    if (!/\.(glb|gltf)$/i.test(f.name)) {
      setError("请上传 .glb 或 .gltf 文件");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const id = await ensureTask();
      const u = await api.uploadFile(id, "model", f);
      setModel(u);
      await api.patchTask(id, { name: params.name || null, params, inputs: [u, ...extras] });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const onExtras = async (list: FileList | null) => {
    if (!list?.length) return;
    setBusy(true);
    setError(null);
    try {
      const id = await ensureTask();
      const ups: UploadedFile[] = [];
      for (const f of Array.from(list)) ups.push(await api.uploadFile(id, "aux", f));
      const next = [...extras, ...ups];
      setExtras(next);
      await api.patchTask(id, { inputs: model ? [model, ...next] : next });
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    setError(null);

    // 前端预检
    const checks: string[] = [];
    if (!model) checks.push("请上传一个 .glb 或 .gltf 3D 模型文件");
    if (!params.name?.trim()) checks.push("请输入任务名称");
    if (checks.length) {
      setError(checks.join("\n"));
      return;
    }

    setBusy(true);
    try {
      const id = await ensureTask();
      await api.patchTask(id, {
        name: params.name || null,
        params,
        inputs: model ? [model, ...extras] : extras,
      });
      await api.runTask(id);
      // 成功 → 跳转详情页
      window.location.href = `/tasks/${id}`;
    } catch (e: any) {
      const msg = e?.message || String(e);
      console.error("[start] 启动失败:", e);  // 调试用, 控制台可查
      setError(msg.includes("\n") ? msg : `启动失败: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <section className="card p-6 lg:col-span-2">
        <h1 className="text-lg font-semibold mb-4">新建任务</h1>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <label className="md:col-span-2">
            <span className="label">任务名称</span>
            <input className="input" value={params.name || ""}
              onChange={(e) => setParams({ ...params, name: e.target.value })}
              placeholder="例:角色头模型磨损 v3" />
          </label>

          <Section title="渲染" />

          <NumberField label="渲染分辨率" value={params.resolution}
            onChange={(v) => setParams({ ...params, resolution: v })} />
          <NumberField label="Cycles 采样数" value={params.samples}
            onChange={(v) => setParams({ ...params, samples: v })} />
          <NumberField label="相机距离" step={0.1} value={params.cam_distance}
            onChange={(v) => setParams({ ...params, cam_distance: v })} />
          <Checkbox label="启用 ComfyUI inpaint" checked={params.enable_inpaint}
            onChange={(v) => setParams({ ...params, enable_inpaint: v })} />
          <Checkbox label="重建前需确认 (防 AI 断连)" checked={params.confirm_before_reconstruct}
            onChange={(v) => setParams({ ...params, confirm_before_reconstruct: v })} />

          <Section title="纹理重建" />

          <label>
            <span className="label">目标 mesh 名称</span>
            <input className="input font-mono" value={params.target_object}
              onChange={(e) => setParams({ ...params, target_object: e.target.value })} />
          </label>
          <NumberField label="贴图分辨率 (TEX_SIZE)" value={params.tex_size}
            onChange={(v) => setParams({ ...params, tex_size: v })} />
          <NumberField label="Inpaint 迭代次数" value={params.inpaint_iters}
            onChange={(v) => setParams({ ...params, inpaint_iters: v })} />
          <NumberField label="UV 接缝渗色 (px)" value={params.seam_dilate}
            onChange={(v) => setParams({ ...params, seam_dilate: v })} />
          <NumberField label="朝向阈值 FACING_MIN" step={0.01} value={params.facing_min}
            onChange={(v) => setParams({ ...params, facing_min: v })} />
          <NumberField label="遮挡阈值 OCCLUSION_REL" step={0.01} value={params.occlusion_rel}
            onChange={(v) => setParams({ ...params, occlusion_rel: v })} />
          <Checkbox label="保存调试图 (debug)" checked={params.save_debug}
            onChange={(v) => setParams({ ...params, save_debug: v })} />
          <label>
            <span className="label">遮罩去噪</span>
            <select className="input" value={params.mask_denoise}
              onChange={(e) => setParams({ ...params, mask_denoise: e.target.value })}>
              <option value="off">关闭</option>
              <option value="light">轻度</option>
              <option value="medium">中度 (推荐)</option>
              <option value="strong">强力</option>
            </select>
          </label>
          <label>
            <span className="label">最终贴图基名</span>
            <input className="input font-mono" value={params.final_name}
              onChange={(e) => setParams({ ...params, final_name: e.target.value })} />
          </label>
          <label className="md:col-span-2">
            <span className="label">Workflow 覆盖路径 (可选)</span>
            <input className="input font-mono" value={params.workflow_override || ""}
              onChange={(e) => setParams({ ...params, workflow_override: e.target.value })}
              placeholder="留空则使用配置页或内置 wear.json" />
          </label>
        </div>

        {/* ===== 磨损强度控制 (方案 C: 独立区块) ===== */}
        <div className="mt-6 p-5 rounded-lg border border-ink-600 bg-ink-800/50">
          <h3 className="text-sm font-semibold mb-4 text-slate-200">磨损强度控制</h3>

          {/* 生图模型选择 */}
          <div className="mb-4">
            <span className="label">生图模型</span>
            <div className="grid grid-cols-3 gap-2 mt-1.5">
              {wearModels.map((m) => (
                <button
                  key={m.key}
                  type="button"
                  title={m.desc}
                  onClick={() => setParams({ ...params, wear_model: m.key })}
                  className={`px-3 py-2 text-xs rounded-md border transition-all text-left ${
                    params.wear_model === m.key
                      ? "bg-accent-600 border-accent-400 text-white shadow-sm shadow-accent-500/20"
                      : "bg-ink-700 border-ink-500 text-slate-400 hover:bg-ink-600 hover:text-slate-200"
                  }`}
                >
                  <div className="font-medium">{m.label}</div>
                  <div className="text-[10px] opacity-70 mt-0.5 leading-tight">{m.desc}</div>
                </button>
              ))}
              {wearModels.length === 0 && (
                <span className="text-xs text-slate-500 col-span-3">加载模型列表中...</span>
              )}
            </div>
          </div>

          {/* 预设 */}
          <div className="mb-4">
            <span className="label">快捷预设</span>
            <div className="flex gap-2 mt-1.5">
              {([
                { key: "light", label: "轻微", value: 20 },
                { key: "medium", label: "中等", value: 50 },
                { key: "heavy", label: "严重", value: 85 },
              ] as const).map((p) => (
                <button
                  key={p.key}
                  type="button"
                  onClick={() => setParams({ ...params, wear_preset: p.key, wear_intensity: p.value })}
                  className={`px-4 py-1.5 text-xs rounded-md border transition-all ${
                    params.wear_preset === p.key
                      ? "bg-accent-600 border-accent-400 text-white shadow-sm shadow-accent-500/20"
                      : "bg-ink-700 border-ink-500 text-slate-400 hover:bg-ink-600 hover:text-slate-200"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Slider */}
          <div className="mb-4">
            <div className="flex justify-between items-center mb-1.5">
              <span className="label">强度</span>
              <span className="text-sm font-mono tabular-nums text-accent-400 font-semibold">
                {params.wear_intensity}%
              </span>
            </div>
            <input
              type="range" min={0} max={100} step={1}
              value={params.wear_intensity}
              onChange={(e) => setParams({ ...params, wear_intensity: Number(e.target.value), wear_preset: "custom" })}
              className="wear-slider"
            />
            <div className="flex justify-between text-[11px] text-slate-500 mt-1">
              <span>几乎无磨损</span>
              <span>标准</span>
              <span>重度磨损</span>
            </div>
          </div>

          {/* 材质 */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <span className="label">材质类型</span>
              <select
                className="input mt-1"
                value={params.material_type}
                onChange={(e) => setParams({ ...params, material_type: e.target.value })}
              >
                <option value="metal">金属</option>
                <option value="plastic">塑料</option>
                <option value="wood">木材</option>
                <option value="ceramic">陶瓷</option>
              </select>
            </div>
            <div>
              <span className="label">当前预设</span>
              <input className="input mt-1 font-mono" value={params.wear_preset} readOnly />
            </div>
          </div>
        </div>

        <div className="mt-6 flex items-center gap-3">
          <button className="btn-primary" onClick={start} disabled={busy || !model}>开始任务</button>
          {taskId && <span className="text-xs text-slate-400 font-mono">task_id: {taskId}</span>}
        </div>
        {error && (
          <div className="mt-3 p-3 rounded-lg bg-rose-900/20 border border-rose-800/40">
            <p className="text-xs font-semibold text-rose-300 mb-1">⚠ 请修正以下问题:</p>
            {error.split("\n").map((line, i) => (
              <p key={i} className="text-sm text-rose-200/90 ml-2">
                {line.startsWith("• ") || line.startsWith("- ") ? line : `• ${line}`}
              </p>
            ))}
          </div>
        )}
      </section>

      <aside className="card p-6">
        <h2 className="text-base font-semibold mb-3">输入素材</h2>

        <div className="mb-4">
          <span className="label">GLB / GLTF 模型 (必选)</span>
          <input
            type="file"
            accept=".glb,.gltf"
            onChange={(e) => onModel(e.target.files?.[0] || null)}
            className="block w-full text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:bg-accent-600 file:text-white hover:file:bg-accent-500"
          />
          {model && <div className="mt-2 text-xs font-mono text-emerald-300">✓ {model.name} ({(model.size / 1024 / 1024).toFixed(2)} MB)</div>}
        </div>

        <div className="mb-2">
          <span className="label">附加资源 (可选)</span>
          <input
            type="file"
            multiple
            onChange={(e) => onExtras(e.target.files)}
            className="block w-full text-xs text-slate-300 file:mr-3 file:py-1.5 file:px-3 file:rounded-md file:border-0 file:bg-ink-600 file:text-slate-100 hover:file:bg-ink-500"
          />
        </div>
        {extras.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs font-mono">
            {extras.map((f) => (
              <li key={f.relative_path} className="flex justify-between text-slate-300">
                <span className="truncate">{f.role}/{f.name}</span>
                <span className="text-slate-500">{(f.size / 1024).toFixed(1)} KB</span>
              </li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}

function Section({ title }: { title: string }): React.ReactElement {
  return (
    <div className="md:col-span-2 mt-2 text-xs font-semibold uppercase tracking-wider text-slate-500">
      {title}
    </div>
  );
}

function NumberField({ label, value, onChange, step = 1 }: { label: string; value: number; onChange: (v: number) => void; step?: number }) {
  return (
    <label>
      <span className="label">{label}</span>
      <input type="number" step={step} className="input" value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  );
}

function Checkbox({ label, checked, onChange }: { label: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 mt-6">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="text-sm">{label}</span>
    </label>
  );
}

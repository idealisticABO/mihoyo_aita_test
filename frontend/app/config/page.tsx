"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AppConfig } from "@/lib/types";

const FIELDS: Array<{ key: keyof AppConfig; label: string; placeholder?: string; help?: string }> = [
  { key: "blender_executable", label: "Blender 可执行文件路径", placeholder: "C:/Program Files/Blender Foundation/Blender 4.x/blender.exe", help: "必填,渲染与重建都依赖它。" },
  { key: "comfyui_base_url", label: "ComfyUI 地址", placeholder: "http://127.0.0.1:8188" },
  { key: "comfyui_workflow", label: "ComfyUI workflow JSON (可选)", placeholder: "留空则使用内置 wear.json", help: "覆盖默认 workflow,文件需在后端可访问的绝对路径。" },
  { key: "python_executable", label: "Python (可选,诊断用)", placeholder: "python 或绝对路径" },
  { key: "output_dir", label: "输出目录" },
  { key: "temp_dir", label: "临时目录" },
];

export default function ConfigPage() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    api.getConfig().then(setCfg).catch((e) => setMsg(String(e)));
  }, []);

  if (!cfg) return <div className="text-slate-400 text-sm">Loading…</div>;

  const save = async () => {
    setSaving(true);
    setMsg(null);
    try {
      const updated = await api.updateConfig(cfg);
      setCfg(updated);
      setMsg("✓ 已保存");
    } catch (e) {
      setMsg(`保存失败: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="card p-6 max-w-3xl mx-auto">
      <h1 className="text-lg font-semibold mb-1">系统配置</h1>
      <p className="text-sm text-slate-400 mb-6">
        Blender 必填,ComfyUI workflow 留空将使用内置 wear.json。模型、render.py、reconstruct.py 全部由后端模板自动生成,无需手动配置脚本路径。
      </p>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {FIELDS.map((f) => (
          <label key={String(f.key)} className={["comfyui_base_url", "comfyui_workflow"].includes(String(f.key)) ? "md:col-span-2" : ""}>
            <span className="label">{f.label}</span>
            <input
              className="input font-mono"
              placeholder={f.placeholder}
              value={(cfg[f.key] as string) || ""}
              onChange={(e) => setCfg({ ...cfg, [f.key]: e.target.value || null })}
            />
            {f.help && <span className="text-[11px] text-slate-500 mt-1 block">{f.help}</span>}
          </label>
        ))}
      </div>
      <div className="mt-6 flex items-center gap-3">
        <button className="btn-primary" onClick={save} disabled={saving}>
          {saving ? "保存中…" : "保存配置"}
        </button>
        {msg && <span className="text-sm text-slate-300">{msg}</span>}
      </div>
    </div>
  );
}

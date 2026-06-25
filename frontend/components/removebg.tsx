"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Task, ViewState } from "@/lib/types";

const METHODS: { key: string; label: string; desc: string }[] = [
  { key: "inspyrenet", label: "InspyrenetRembg", desc: "通用前景检测,速度快" },
  { key: "bria", label: "BRIA RMBG", desc: "商用模型,边缘细节好" },
  { key: "sam", label: "SAM + GroundingDINO", desc: "文本驱动,精确但慢" },
];

/** 去背景弹窗: 跑三种方式 + 选择 + 替换 inpaint 输入 */
export function RemoveBgDialog({
  task,
  view,
  onClose,
  onUpdated,
}: {
  task: Task;
  view: ViewState;
  onClose: () => void;
  onUpdated: (t: Task) => void;
}) {
  const [prompt, setPrompt] = useState(task.name || "foreground object");
  const [running, setRunning] = useState(false);
  const [enabled, setEnabled] = useState<Record<string, boolean>>({
    inspyrenet: true,
    bria: true,
    sam: true,
  });
  const [bump, setBump] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const candidates = view.bg_candidates || {};
  const selectedMethod = (() => {
    if (!view.bg_removed_path) return "none";
    for (const [k, v] of Object.entries(candidates)) {
      if (v === view.bg_removed_path) return k;
    }
    return "none";
  })();

  // ESC 关闭
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async () => {
    const methods = METHODS.filter((m) => enabled[m.key]).map((m) => m.key);
    if (methods.length === 0) {
      setError("至少选择一种方法");
      return;
    }
    setRunning(true);
    setError(null);
    try {
      await api.removeBgRun(task.id, view.cam, prompt, methods);
      // 后端是后台跑,通过 WebSocket 推送 task.update,这里仅给一个 hint
      // 父组件会收到 updated 事件并刷新 task.views
      setBump(Date.now());
    } catch (e: any) {
      setError(String(e?.message || e));
    } finally {
      setRunning(false);
    }
  };

  const select = async (method: string) => {
    try {
      const updated = await api.selectBg(task.id, view.cam, method);
      onUpdated(updated);
    } catch (e: any) {
      setError(String(e?.message || e));
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative w-[92vw] max-w-4xl max-h-[88vh] overflow-y-auto rounded-xl border border-slate-700 bg-slate-950 p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-slate-200">
            ✂ 去除背景 — {view.cam}
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-200 text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {/* prompt + 方法勾选 */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">
              SAM 抠图 prompt (中文会自动翻译)
            </label>
            <input
              className="input w-full"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="如: 豹子 / chameleon / a sword"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">启用方法</label>
            <div className="flex gap-2 flex-wrap">
              {METHODS.map((m) => (
                <label
                  key={m.key}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-ink-600 bg-ink-900 cursor-pointer"
                  title={m.desc}
                >
                  <input
                    type="checkbox"
                    checked={!!enabled[m.key]}
                    onChange={(e) =>
                      setEnabled({ ...enabled, [m.key]: e.target.checked })
                    }
                  />
                  <span>{m.label}</span>
                </label>
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3 mb-4">
          <button
            className="btn-primary text-sm bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50"
            disabled={running}
            onClick={run}
          >
            {running ? "提交中…" : "▶ 运行"}
          </button>
          <span className="text-xs text-slate-500">
            提交后在后台跑,结果会通过 WebSocket 推送到这里
          </span>
        </div>

        {error && (
          <div className="mb-3 px-3 py-2 rounded bg-rose-900/30 border border-rose-800/30 text-xs text-rose-300">
            {error}
          </div>
        )}

        {/* 候选结果 */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {/* 不去背景选项 */}
          <CandidateCard
            label="(不去背景)"
            desc="使用原渲染图作为 inpaint 输入"
            url=""
            selected={selectedMethod === "none"}
            onClick={() => select("none")}
          />
          {METHODS.map((m) => {
            const rel = candidates[m.key];
            const url = rel ? api.filePathToUrl(task.id, rel) : "";
            return (
              <CandidateCard
                key={m.key}
                label={m.label}
                desc={m.desc}
                url={url ? `${url}${bump ? `&_=${bump}` : ""}` : ""}
                selected={selectedMethod === m.key}
                disabled={!url}
                onClick={() => url && select(m.key)}
              />
            );
          })}
        </div>

        <div className="mt-4 text-xs text-slate-500">
          选中后,本视角的 inpaint 阶段会用所选去背景图作为输入。点"(不去背景)"取消。
        </div>
      </div>
    </div>
  );
}

function CandidateCard({
  label,
  desc,
  url,
  selected,
  disabled,
  onClick,
}: {
  label: string;
  desc: string;
  url: string;
  selected: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  const border = selected
    ? "border-emerald-500 ring-2 ring-emerald-500/40"
    : disabled
    ? "border-ink-700 opacity-40"
    : "border-ink-600 hover:border-slate-400";
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`text-left rounded-lg bg-ink-900 border ${border} p-2 transition`}
    >
      <div className="aspect-square bg-ink-800 rounded border border-ink-700 mb-2 overflow-hidden flex items-center justify-center">
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={url} alt={label} className="w-full h-full object-contain" />
        ) : (
          <span className="text-[10px] text-slate-600">
            {disabled ? "(未生成)" : "(原渲染图)"}
          </span>
        )}
      </div>
      <div className="flex items-center gap-1">
        {selected && <span className="text-emerald-400 text-xs">✓</span>}
        <span className="text-sm text-slate-200">{label}</span>
      </div>
      <div className="text-[10px] text-slate-500 mt-1">{desc}</div>
    </button>
  );
}

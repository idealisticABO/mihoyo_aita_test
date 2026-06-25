"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import dynamic from "next/dynamic";
import { api } from "@/lib/api";
import type { Task, ViewState } from "@/lib/types";
import { StatusBadge } from "@/components/statusbadge";

const ModelViewer = dynamic(() => import("@/components/modelviewer").then((m) => ({ default: m.ModelViewer })), {
  ssr: false,
  loading: () => null,
});

export default function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<Task | null>(null);
  const [logs, setLogs] = useState<string[]>([]);
  const [bumps, setBumps] = useState<Record<string, number>>({}); // for cache-busting <img>
  const [wearModels, setWearModels] = useState<{ key: string; label: string }[]>([]);
  const [regenModel, setRegenModel] = useState<string>("");  // "" = 使用任务默认
  const [viewerOpen, setViewerOpen] = useState(false);  // 3D 预览弹窗
  const logBoxRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    api.getWorkflowModels().then((r) => setWearModels(r.items)).catch(() => {});
  }, []);

  useEffect(() => {
    if (!id) return;
    api.getTask(id).then(setTask).catch(() => undefined);
    const ws = new WebSocket(api.wsUrl(id));
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data);
        if (msg.event === "snapshot" || msg.event === "updated" || msg.event === "created") {
          setTask(msg.task);
        } else if (msg.event === "log") {
          setLogs((prev) => [...prev.slice(-2000), msg.line]);
        }
      } catch {
        /* ignore */
      }
    };
    return () => ws.close();
  }, [id]);

  useEffect(() => {
    if (logBoxRef.current) logBoxRef.current.scrollTop = logBoxRef.current.scrollHeight;
  }, [logs]);

  if (!task) return <div className="text-slate-400 text-sm">Loading…</div>;

  const stageOf = (n: string) => task.stages.find((s) => s.name === n);

  const regenerate = async (cam: string) => {
    try {
      await api.regenerateView(task.id, cam, regenModel || undefined);
      setBumps((b) => ({ ...b, [cam]: Date.now() }));
    } catch (e) {
      alert(String(e));
    }
  };

  // GLB 3D 预览 URL
  const glbs = task.outputs?.glb || [];
  const glbUrl = glbs.length > 0
    ? `/api/tasks/${task.id}/files/textures/${encodeURIComponent(glbs[0].split("/").pop() || glbs[0])}`
    : "";

  return (
    <div className="space-y-6">
      <header className="card p-5 flex items-start justify-between gap-4">
        <div>
          <div className="text-xs text-slate-500 font-mono">{task.id}</div>
          <h1 className="text-xl font-semibold">{task.name || "(未命名任务)"}</h1>
          <div className="mt-2 flex items-center gap-3 text-sm">
            <StatusBadge status={task.status} />
            <span className="text-slate-400">创建于 {new Date(task.created_at).toLocaleString()}</span>
            {task.error && (
              <div className="mt-2 p-2 rounded bg-rose-900/25 border border-rose-800/30">
                <span className="text-rose-300 text-xs">⚠ {task.error}</span>
              </div>
            )}
          </div>
        </div>
        <div className="flex gap-2 flex-wrap">
          {/* ---- awaiting_confirm: 只能确认重建 ---- */}
          {task.status === "awaiting_confirm" && (
            <button
              className="btn-primary text-sm bg-emerald-600 hover:bg-emerald-500"
              onClick={() => api.continueTask(task.id).catch((e) => alert(String(e)))}
            >
              ✓ 确认重建
            </button>
          )}

          {/* ---- completed + 有 GLB: 3D 预览 ---- */}
          {glbUrl && task.status === "completed" && (
            <button
              className="btn-primary text-sm bg-indigo-600 hover:bg-indigo-500"
              onClick={() => setViewerOpen(true)}
            >
              🧊 3D 预览
            </button>
          )}

          {/* ---- completed/failed/cancelled + inpaint 已完成: 重新重建 ---- */}
          {(() => {
            const inpaintDone = task.stages.find(s => s.name === "inpaint");
            const canReconstruct = task.status !== "awaiting_confirm"
              && ["completed", "failed", "cancelled"].includes(task.status)
              && inpaintDone && ["completed", "skipped"].includes(inpaintDone.status);
            if (!canReconstruct) return null;
            return (
              <button
                key="reconstruct"
                className="btn-primary text-sm bg-cyan-600 hover:bg-cyan-500"
                onClick={() => api.reconstructTask(task.id).catch((e) => alert(String(e)))}
              >
                🔄 重新重建
              </button>
            );
          })()}

          {/* ---- pending/queued: 启动 ---- */}
          {["pending", "queued"].includes(task.status) && (
            <button className="btn-primary text-sm" onClick={() => api.runTask(task.id).catch((e) => alert(String(e)))}>▶ 启动</button>
          )}

          {/* ---- failed: 重试 ---- */}
          {task.status === "failed" && (
            <button className="btn-primary text-sm bg-amber-600 hover:bg-amber-500" onClick={() => api.retryTask(task.id).catch((e) => alert(String(e)))}>🔁 重试</button>
          )}

          {/* ---- running 中: 取消 ---- */}
          {["running", "rendering", "inpainting", "reconstructing"].includes(task.status) && (
            <button className="btn-ghost text-sm text-rose-300 border border-rose-800/40" onClick={() => api.cancelTask(task.id).catch((e) => alert(String(e)))}>✕ 取消</button>
          )}

          {/* ---- 调试区: 强制重置 (折叠到 ⋯ 菜单) ---- */}
          {task.status !== "pending" && task.status !== "queued" && (
            <button
              className="btn-ghost text-xs text-slate-500 hover:text-slate-300"
              onClick={async () => {
                if (!confirm("强制把任务标记为 failed, 解除卡死状态?\n\n此操作仅用于调试,不会停止正在运行的进程。")) return;
                try { await api.resetTask(task.id); } catch (e) { alert(String(e)); }
              }}
            >
              ⚙ 强制重置
            </button>
          )}
        </div>
      </header>

      <section className="grid grid-cols-3 gap-4">
        {["render", "inpaint", "reconstruct"].map((s) => {
          const st = stageOf(s);
          return (
            <div key={s} className="card p-4">
              <div className="flex items-center justify-between">
                <span className="font-medium capitalize">{s}</span>
                <span className="text-xs text-slate-400">{st?.status || "-"}</span>
              </div>
              <div className="mt-2 text-xs text-slate-500">{st?.outputs.length || 0} 个产物</div>
              {st?.error && <div className="mt-1 text-xs text-rose-300">{st.error}</div>}
            </div>
          );
        })}
      </section>

      <section className="card p-5">
        <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
          <h2 className="text-base font-semibold">六视角</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400">重新生成用模型:</span>
            <select
              className="input text-xs py-1 w-auto"
              value={regenModel}
              onChange={(e) => setRegenModel(e.target.value)}
            >
              <option value="">任务默认 ({task.params.wear_model || "nano_banana"})</option>
              {wearModels.map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {task.views.map((v) => (
            <ViewCard key={v.cam} task={task} view={v} bump={bumps[v.cam] || 0} onRegenerate={() => regenerate(v.cam)} />
          ))}
        </div>
      </section>

      <section className="card p-5">
        <h2 className="text-base font-semibold mb-3">日志</h2>
        <pre
          ref={logBoxRef}
          className="bg-ink-900 border border-ink-600 rounded-lg p-3 text-xs font-mono h-80 overflow-auto whitespace-pre-wrap"
        >
          {logs.join("\n") || "(等待日志)"}
        </pre>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <OutputGroup task={task} kind="textures" title="最终贴图" />
        <OutputGroup task={task} kind="debug" title="调试图 (dbg_*)" />
      </section>

      {viewerOpen && glbUrl && (
        <ModelViewer url={glbUrl} onClose={() => setViewerOpen(false)} />
      )}
    </div>
  );
}

function ViewCard({
  task,
  view,
  bump,
  onRegenerate,
}: {
  task: Task;
  view: ViewState;
  bump: number;
  onRegenerate: () => void;
}) {
  const renderUrl = view.render_path ? api.filePathToUrl(task.id, view.render_path) : "";
  const inpaintUrl = view.inpaint_path
    ? `${api.filePathToUrl(task.id, view.inpaint_path)}${bump ? `&_=${bump}` : ""}`
    : "";
  const aiWearUrl = view.ai_wear_path
    ? `${api.filePathToUrl(task.id, view.ai_wear_path)}${bump ? `&_=${bump}` : ""}`
    : "";

  const statusColor: Record<string, string> = {
    pending: "text-slate-400",
    running: "text-amber-300 animate-pulse",
    completed: "text-emerald-300",
    failed: "text-rose-300",
    skipped: "text-slate-500",
  };

  return (
    <div className="rounded-lg bg-ink-900 border border-ink-600 p-3">
      <div className="flex items-center justify-between mb-2">
        <span className="font-mono text-sm">{view.cam}</span>
        <span className={`text-xs ${statusColor[view.inpaint_status]}`}>{view.inpaint_status}</span>
      </div>

      <div className="grid grid-cols-3 gap-1">
        <Thumb label="render" url={renderUrl} />
        <Thumb label="AI wear" url={aiWearUrl} />
        <Thumb label="mask" url={inpaintUrl} />
      </div>

      {view.error && <div className="mt-2 text-xs text-rose-300 truncate" title={view.error}>{view.error}</div>}

      <button
        onClick={onRegenerate}
        disabled={view.inpaint_status === "running" || !view.render_path}
        className="btn-ghost text-xs w-full mt-3 disabled:opacity-50"
      >
        重新生成 inpaint
      </button>
    </div>
  );
}

function Thumb({ label, url }: { label: string; url: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase text-slate-500 mb-1">{label}</div>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="block aspect-square bg-ink-800 rounded border border-ink-600 overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={url} alt={label} className="w-full h-full object-contain" />
        </a>
      ) : (
        <div className="aspect-square bg-ink-800 rounded border border-ink-600 flex items-center justify-center text-[10px] text-slate-600">
          (空)
        </div>
      )}
    </div>
  );
}

function OutputGroup({ task, kind, title }: { task: Task; kind: "textures" | "debug"; title: string }) {
  const items = task.outputs[kind] || [];
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium">{title}</span>
        <span className="text-xs text-slate-500">{items.length}</span>
      </div>
      {items.length === 0 ? (
        <div className="text-xs text-slate-500">暂无</div>
      ) : (
        <ul className="grid grid-cols-2 gap-2">
          {items.map((p) => {
            const url = api.filePathToUrl(task.id, p);
            const name = p.split("/").pop() || p;
            return (
              <li key={p} className="text-xs">
                <a href={url} target="_blank" rel="noreferrer" className="block">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={url} alt={name} className="rounded border border-ink-600 bg-ink-900 aspect-square object-contain" />
                  <div className="mt-1 truncate font-mono" title={name}>{name}</div>
                </a>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

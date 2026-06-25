import type { TaskStatus } from "@/lib/types";

const COLORS: Record<TaskStatus, string> = {
  pending: "bg-slate-600/40 text-slate-300",
  queued: "bg-indigo-600/30 text-indigo-200",
  running: "bg-amber-500/30 text-amber-200",
  rendering: "bg-amber-500/30 text-amber-200",
  inpainting: "bg-fuchsia-500/30 text-fuchsia-200",
  awaiting_confirm: "bg-yellow-400/30 text-yellow-200 ring-1 ring-yellow-400/50",
  reconstructing: "bg-cyan-500/30 text-cyan-200",
  completed: "bg-emerald-500/30 text-emerald-200",
  failed: "bg-rose-500/30 text-rose-200",
  cancelled: "bg-slate-500/30 text-slate-300",
};

const LABELS: Partial<Record<TaskStatus, string>> = {
  awaiting_confirm: "等待确认",
  rendering: "渲染中",
  inpainting: "AI 生成中",
  reconstructing: "重建中",
  completed: "已完成",
  failed: "失败",
};

export function StatusBadge({ status }: { status: TaskStatus }) {
  return (
    <span className={`px-2 py-0.5 text-xs rounded-md font-medium ${COLORS[status]}`}>
      {LABELS[status] ?? status}
    </span>
  );
}

"use client";

import Link from "next/link";
import useSWR from "swr";
import { api } from "@/lib/api";
import { TaskList } from "@/components/tasklist";

const fetcher = () => api.probe();

function ProbeRow({ label, ok, detail }: { label: string; ok: boolean; detail?: string }) {
  return (
    <div className="flex items-center justify-between py-2 text-sm">
      <span className="text-slate-300">{label}</span>
      <span className="flex items-center gap-2">
        <span className={`w-2 h-2 rounded-full ${ok ? "bg-emerald-400" : "bg-rose-400"}`} />
        <span className="text-xs text-slate-400 truncate max-w-[260px]" title={detail || ""}>
          {ok ? detail || "ready" : detail || "not configured"}
        </span>
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const { data: probe } = useSWR("probe", fetcher, { refreshInterval: 10000 });

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <section className="card p-5 lg:col-span-2">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold">最近任务</h2>
          <Link href="/tasks/new" className="btn-primary text-sm">+ 新建任务</Link>
        </div>
        <TaskList />
      </section>

      <section className="card p-5">
        <h2 className="text-base font-semibold mb-3">系统状态</h2>
        {probe ? (
          <div className="divide-y divide-ink-600">
            <ProbeRow label="Blender" ok={probe.blender.ok} detail={probe.blender.resolved || probe.blender.reason || undefined} />
            <ProbeRow label="ComfyUI" ok={probe.comfyui.ok} detail={String(probe.comfyui.status ?? probe.comfyui.reason ?? "")} />
            <ProbeRow label="Workflow JSON" ok={probe.comfyui_workflow.ok} detail={probe.comfyui_workflow.resolved || probe.comfyui_workflow.reason || undefined} />
            <ProbeRow label="Python (诊断)" ok={probe.python.ok} detail={probe.python.resolved || probe.python.reason || undefined} />
          </div>
        ) : (
          <div className="text-slate-400 text-sm">检测中…</div>
        )}
        <div className="mt-4">
          <Link href="/config" className="btn-ghost text-sm w-full">前往配置</Link>
        </div>
      </section>
    </div>
  );
}

"use client";

import Link from "next/link";
import useSWR from "swr";
import { api } from "@/lib/api";
import { StatusBadge } from "./statusbadge";

const fetcher = () => api.listTasks().then((r) => r.items);

export function TaskList() {
  const { data, isLoading, error } = useSWR("tasks", fetcher, { refreshInterval: 4000 });

  if (isLoading) return <div className="text-slate-400 text-sm">Loading…</div>;
  if (error) return <div className="text-rose-400 text-sm">加载失败: {String(error)}</div>;
  if (!data?.length) return <div className="text-slate-400 text-sm">还没有任务,点右上角新建。</div>;

  return (
    <div className="divide-y divide-ink-600">
      {data.map((t) => (
        <Link
          key={t.id}
          href={`/tasks/${t.id}`}
          className="flex items-center justify-between py-3 px-2 hover:bg-ink-700/50 rounded-lg"
        >
          <div>
            <div className="font-medium">{t.name || t.id}</div>
            <div className="text-xs text-slate-500 font-mono">{t.id}</div>
          </div>
          <div className="flex items-center gap-4">
            <span className="text-xs text-slate-400">
              {new Date(t.created_at).toLocaleString()}
            </span>
            <StatusBadge status={t.status} />
          </div>
        </Link>
      ))}
    </div>
  );
}

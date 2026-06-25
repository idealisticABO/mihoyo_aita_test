"use client";

import Link from "next/link";
import { useState, useCallback } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { StatusBadge } from "./statusbadge";
import type { Task } from "@/lib/types";

const fetcher = () => api.listTasks().then((r) => r.items);

export function TaskList() {
  const { data, isLoading, error, mutate } = useSWR("tasks", fetcher, { refreshInterval: 4000 });

  if (isLoading) return <div className="text-slate-400 text-sm">Loading…</div>;
  if (error) return <div className="text-rose-400 text-sm">加载失败: {String(error)}</div>;
  if (!data?.length) return <div className="text-slate-400 text-sm">还没有任务,点右上角新建。</div>;

  return (
    <div className="divide-y divide-ink-600">
      {data.map((t) => (
        <TaskRow key={t.id} task={t} onMutate={mutate} />
      ))}
    </div>
  );
}

function TaskRow({ task, onMutate }: { task: Task; onMutate: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(task.name || "");
  const [deleting, setDeleting] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const saveName = useCallback(async () => {
    const trimmed = name.trim();
    if (!trimmed || trimmed === (task.name || "")) {
      setName(task.name || "");
      setEditing(false);
      return;
    }
    try {
      await api.patchTask(task.id, { name: trimmed });
      setEditing(false);
      onMutate();
    } catch {
      setName(task.name || "");
      setEditing(false);
    }
  }, [name, task.id, task.name, onMutate]);

  const handleDelete = useCallback(async () => {
    try {
      await api.deleteTask(task.id);
      onMutate();
    } catch {
      // silently fail
    }
    setDeleting(false);
    setConfirmDelete(false);
  }, [task.id, onMutate]);

  return (
    <div className="group flex items-center justify-between py-3 px-2 hover:bg-ink-700/50 rounded-lg">
      <div className="flex-1 min-w-0 mr-2">
        {editing ? (
          <input
            className="input w-full text-sm font-medium"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={saveName}
            onKeyDown={(e) => {
              if (e.key === "Enter") { e.preventDefault(); saveName(); }
              if (e.key === "Escape") { setName(task.name || ""); setEditing(false); }
            }}
            autoFocus
          />
        ) : (
          <button
            onClick={() => { setName(task.name || ""); setEditing(true); }}
            className="text-left w-full"
            title="点击重命名"
          >
            <div className="font-medium truncate">{task.name || task.id}</div>
            <div className="text-xs text-slate-500 font-mono truncate">{task.id}</div>
          </button>
        )}
      </div>
      <div className="flex items-center gap-2 flex-shrink-0">
        <span className="text-xs text-slate-400 hidden sm:inline">
          {new Date(task.created_at).toLocaleString()}
        </span>
        <StatusBadge status={task.status} />
        <Link
          href={`/tasks/${task.id}`}
          className="text-xs px-2 py-1 rounded bg-ink-800 hover:bg-ink-700 text-slate-300"
        >
          详情
        </Link>
        {confirmDelete ? (
          <div className="flex items-center gap-1">
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="text-xs px-2 py-1 rounded bg-rose-700 hover:bg-rose-600 text-white"
            >
              确认
            </button>
            <button
              onClick={() => setConfirmDelete(false)}
              className="text-xs px-2 py-1 rounded bg-ink-700 hover:bg-ink-600 text-slate-300"
            >
              取消
            </button>
          </div>
        ) : (
          <button
            onClick={() => setConfirmDelete(true)}
            className="opacity-0 group-hover:opacity-100 transition text-xs px-2 py-1 rounded bg-rose-900/50 hover:bg-rose-800/60 text-rose-400"
            title="删除任务"
          >
            删除
          </button>
        )}
      </div>
    </div>
  );
}

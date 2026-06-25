import type { AppConfig, ProbeResult, Task, UploadedFile } from "./types";

async function http<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    // 解析 FastAPI {"detail": "..."} 格式
    let msg = text;
    try {
      const j = JSON.parse(text);
      if (j.detail) msg = String(j.detail);
    } catch { /* 不是 JSON, 用原始文本 */ }
    const err = new Error(msg);
    (err as any).status = r.status;
    throw err;
  }
  return (await r.json()) as T;
}

export const api = {
  probe: () => http<ProbeResult>("/api/system/probe"),
  getConfig: () => http<AppConfig>("/api/config"),
  updateConfig: (patch: Partial<AppConfig>) =>
    http<AppConfig>("/api/config", { method: "PUT", body: JSON.stringify(patch) }),

  listTasks: () => http<{ items: Task[]; total: number }>("/api/tasks"),
  createTask: (body: any) => http<Task>("/api/tasks", { method: "POST", body: JSON.stringify(body) }),
  patchTask: (id: string, body: any) =>
    http<Task>(`/api/tasks/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  getTask: (id: string) => http<Task>(`/api/tasks/${id}`),
  runTask: (id: string) => http<Task>(`/api/tasks/${id}/run`, { method: "POST" }),
  retryTask: (id: string) => http<Task>(`/api/tasks/${id}/retry`, { method: "POST" }),
  cancelTask: (id: string) => http<Task>(`/api/tasks/${id}/cancel`, { method: "POST" }),
  continueTask: (id: string) => http<Task>(`/api/tasks/${id}/continue`, { method: "POST" }),
  reconstructTask: (id: string) => http<Task>(`/api/tasks/${id}/reconstruct`, { method: "POST" }),
  regenerateView: (id: string, cam: string, wearModel?: string) =>
    http<Task>(`/api/tasks/${id}/views/${cam}/regenerate${wearModel ? `?wear_model=${wearModel}` : ""}`, { method: "POST" }),
  removeBgRun: (id: string, cam: string, prompt: string, methods: string[]) =>
    http<Task>(
      `/api/tasks/${id}/views/${cam}/remove-bg?prompt=${encodeURIComponent(prompt)}&methods=${methods.join(",")}`,
      { method: "POST" }
    ),
  selectBg: (id: string, cam: string, method: string) =>
    http<Task>(`/api/tasks/${id}/views/${cam}/select-bg?method=${method}`, { method: "POST" }),
  upscaleView: (id: string, cam: string, resolution: number = 2048) =>
    http<Task>(`/api/tasks/${id}/views/${cam}/upscale?resolution=${resolution}`, { method: "POST" }),
  useUpscale: (id: string, cam: string, enabled: boolean) =>
    http<Task>(`/api/tasks/${id}/views/${cam}/use-upscale?enabled=${enabled}`, { method: "POST" }),
  getWorkflowModels: () => http<{ items: { key: string; label: string; desc: string }[] }>("/api/tasks/workflow-models"),
  resetTask: (id: string) => http<Task>(`/api/tasks/${id}/reset`, { method: "POST" }),

  getLogs: (id: string, tail = 500) =>
    fetch(`/api/tasks/${id}/logs?tail=${tail}`).then((r) => r.text()),

  uploadFile: async (taskId: string, role: string, file: File) => {
    const fd = new FormData();
    fd.append("task_id", taskId);
    fd.append("role", role);
    fd.append("file", file);
    const r = await fetch("/api/files/upload", { method: "POST", body: fd });
    if (!r.ok) throw new Error(await r.text());
    return (await r.json()) as UploadedFile;
  },

  fileUrl: (taskId: string, kind: string, name: string, inline = true) =>
    `/api/tasks/${taskId}/files/${kind}/${encodeURIComponent(name)}${inline ? "?inline=true" : ""}`,
  filePathToUrl: (taskId: string, relPath: string, inline = true) => {
    // relPath looks like "outputs/<id>/inpaint/view_cam_front_wear_mask.png"
    const parts = relPath.split("/");
    const idx = parts.indexOf("outputs");
    if (idx < 0 || parts.length < idx + 4) return "";
    const kind = parts[idx + 2];
    const name = parts.slice(idx + 3).join("/");
    return api.fileUrl(taskId, kind, name, inline);
  },

  wsUrl: (taskId: string) => {
    const proto = typeof window !== "undefined" && window.location.protocol === "https:" ? "wss" : "ws";
    const host = typeof window !== "undefined" ? window.location.host : "127.0.0.1:3000";
    return `${proto}://${host}/ws/tasks/${taskId}`;
  },
};

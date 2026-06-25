"""Persistent task manager + WebSocket pub/sub."""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiofiles

from app.config import get_settings
from app.core.paths import task_log_path, task_output_dir, task_upload_dir
from app.models.task import StageState, Task, TaskStatus

logger = logging.getLogger(__name__)


class TaskManager:
    """In-memory store + JSON persistence + simple subscriber bus."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = asyncio.Lock()
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._jobs: dict[str, asyncio.Task] = {}

    @property
    def index_path(self) -> Path:
        return get_settings().data_dir / "tasks.json"

    # ---------- persistence ----------

    async def load(self) -> None:
        async with self._lock:
            if not self.index_path.exists():
                return
            try:
                async with aiofiles.open(self.index_path, "r", encoding="utf-8") as f:
                    raw = await f.read()
                data = json.loads(raw or "[]")
                for item in data:
                    try:
                        t = Task.model_validate(item)
                        # Tasks left running on shutdown are considered failed
                        if t.status in {
                            TaskStatus.running,
                            TaskStatus.rendering,
                            TaskStatus.inpainting,
                            TaskStatus.reconstructing,
                            TaskStatus.queued,
                        }:
                            t.status = TaskStatus.failed
                            t.error = "Interrupted by server restart"
                        self._tasks[t.id] = t
                    except Exception as exc:
                        logger.warning("Skip invalid task in index: %s", exc)
            except Exception as exc:
                logger.warning("Failed to load tasks.json: %s", exc)

    async def _persist(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot = [t.model_dump(mode="json") for t in self._tasks.values()]
        async with aiofiles.open(self.index_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(snapshot, ensure_ascii=False, indent=2))

    # ---------- CRUD ----------

    async def create(self, task: Task) -> Task:
        async with self._lock:
            self._tasks[task.id] = task
            task_upload_dir(get_settings().data_dir, task.id)
            task_output_dir(get_settings().data_dir, task.id)
            await self._persist()
        await self._notify(task.id, {"event": "created", "task": task.model_dump(mode="json")})
        return task

    async def update(self, task: Task) -> None:
        async with self._lock:
            task.touch()
            self._tasks[task.id] = task
            await self._persist()
        await self._notify(task.id, {"event": "updated", "task": task.model_dump(mode="json")})

    async def list(self, limit: int = 100) -> list[Task]:
        items = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        return items[:limit]

    async def get(self, task_id: str) -> Task | None:
        t = self._tasks.get(task_id)
        if t:
            await self._rescue_stale(t)
        return t

    async def _rescue_stale(self, task: Task) -> None:
        """If task looks running but the asyncio job is gone, mark it failed.

        Protects against crashed orchestrator runs that left status stuck in
        rendering / inpainting / reconstructing.
        """
        from datetime import datetime, timezone

        running_states = {
            TaskStatus.queued,
            TaskStatus.running,
            TaskStatus.rendering,
            TaskStatus.inpainting,
            TaskStatus.reconstructing,
        }
        if task.status not in running_states:
            return
        if self.is_job_running(task.id):
            return
        task.status = TaskStatus.failed
        task.error = task.error or "Job ended without updating final state"
        now = datetime.now(timezone.utc)
        if not task.finished_at:
            task.finished_at = now
        for s in task.stages:
            if s.status == "running":
                s.status = "failed"
                s.error = s.error or "orchestrator vanished"
                s.finished_at = now
        await self._persist()
        await self._notify(task.id, {"event": "updated", "task": task.model_dump(mode="json")})

    def is_job_running(self, task_id: str) -> bool:
        job = self._jobs.get(task_id)
        return bool(job and not job.done())

    # ---------- logs ----------

    def log_path(self, task_id: str) -> Path:
        return task_log_path(get_settings().data_dir, task_id)

    async def append_log(self, task_id: str, line: str) -> None:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{ts}] {line}"
        path = self.log_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(path, "a", encoding="utf-8") as f:
            await f.write(formatted + "\n")
        await self._notify(task_id, {"event": "log", "line": formatted})

    async def read_log(self, task_id: str, tail: int | None = None) -> str:
        path = self.log_path(task_id)
        if not path.exists():
            return ""
        async with aiofiles.open(path, "r", encoding="utf-8") as f:
            content = await f.read()
        if tail is None:
            return content
        lines = content.splitlines()
        return "\n".join(lines[-tail:])

    # ---------- pub/sub ----------

    def subscribe(self, task_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=512)
        self._subs[task_id].add(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue) -> None:
        self._subs[task_id].discard(q)

    async def _notify(self, task_id: str, payload: dict[str, Any]) -> None:
        for q in list(self._subs.get(task_id, set())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    # ---------- job tracking ----------

    def attach_job(self, task_id: str, job: asyncio.Task) -> None:
        self._jobs[task_id] = job

    def cancel_job(self, task_id: str) -> bool:
        job = self._jobs.get(task_id)
        if job and not job.done():
            job.cancel()
            return True
        return False

    async def force_reset(self, task_id: str) -> Task | None:
        """User-triggered hard reset for stuck states."""
        from datetime import datetime, timezone

        t = self._tasks.get(task_id)
        if not t:
            return None
        if self.is_job_running(task_id):
            self.cancel_job(task_id)
        now = datetime.now(timezone.utc)
        t.status = TaskStatus.failed
        t.error = "Force reset by user"
        t.finished_at = now
        for s in t.stages:
            if s.status == "running":
                s.status = "failed"
                s.error = "reset"
                s.finished_at = now
        await self._persist()
        await self._notify(task_id, {"event": "updated", "task": t.model_dump(mode="json")})
        return t

    async def shutdown(self) -> None:
        for job in self._jobs.values():
            if not job.done():
                job.cancel()
        await asyncio.gather(*[j for j in self._jobs.values() if not j.done()], return_exceptions=True)


task_manager = TaskManager()

from __future__ import annotations

import json
import multiprocessing as mp
import os
import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from mortal_app.gpu_monitor import GpuMonitor

from .models import RunRequest
from .services import SimulationService, StatisticsService


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def default_data_dir() -> Path:
    configured = os.environ.get("MORTALSIM_DATA_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "MortalSim"
    return Path.home() / ".mortalsim"


@dataclass
class Job:
    run_id: UUID
    request: dict[str, Any]
    created_at: datetime = field(default_factory=utc_now)
    status: str = "queued"
    updated_at: datetime = field(default_factory=utc_now)
    result: dict[str, Any] | None = None
    error: str | None = None
    process: mp.Process | None = None
    process_events: Any = None
    event_log: list[dict[str, Any]] = field(default_factory=list)
    event_condition: threading.Condition = field(default_factory=threading.Condition)
    done: threading.Event = field(default_factory=threading.Event)
    monitor_thread: threading.Thread | None = None
    gpu_monitor: GpuMonitor | None = None
    gpu_summary: dict[str, Any] | None = None

    def publish(self, event: dict[str, Any]) -> None:
        with self.event_condition:
            self.event_log.append(event)
            self.updated_at = utc_now()
            self.event_condition.notify_all()


def worker_entry(request: dict[str, Any], events: Any) -> None:
    """Spawn-safe adapter around the existing simulation worker."""
    try:
        result = SimulationService.run(request, events.put)
        events.put({"type": "completed", "result": result})
    except BaseException:
        events.put({"type": "failed", "error": "worker crashed", "traceback": traceback.format_exc()})


class JobManager:
    def __init__(self, data_dir: Path | None = None):
        self.data_dir = (data_dir or default_data_dir()).resolve()
        self.runs_dir = self.data_dir / "runs"
        self.logs_dir = self.data_dir / "logs"
        self.telemetry_dir = self.data_dir / "telemetry"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.telemetry_dir.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[UUID, Job] = {}
        self.lock = threading.RLock()
        self._load_existing()

    def _load_existing(self) -> None:
        """Restore completed and interrupted run metadata after an app restart."""
        for path in self.runs_dir.glob("*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                run_id = UUID(payload["run_id"])
                created_at = datetime.fromisoformat(payload["created_at"])
                updated_at = datetime.fromisoformat(payload.get("updated_at", payload["created_at"]))
                status = payload.get("status", "failed")
                if status in {"queued", "running"}:
                    status = "failed"
                    payload["error"] = "application restarted before the run completed"
                self.jobs[run_id] = Job(
                    run_id=run_id,
                    request=payload.get("request", {}),
                    created_at=created_at,
                    status=status,
                    updated_at=updated_at,
                    result=payload.get("result"),
                    error=payload.get("error"),
                )
                if status not in {"queued", "running"}:
                    self.jobs[run_id].done.set()
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue

    def create(self, request: RunRequest) -> Job:
        with self.lock:
            active = [job for job in self.jobs.values() if job.status in {"queued", "running"}]
            if active:
                raise RuntimeError("only one simulation can run at a time")
            job = Job(run_id=uuid4(), request=request.model_dump())
            self.jobs[job.run_id] = job
            self._persist(job)
            job.process_events = mp.Queue()
            job.gpu_monitor = GpuMonitor(
                job.publish,
                self.telemetry_dir / f"gpu_{job.run_id}.csv",
            )
            job.gpu_monitor.start()
            job.process = mp.Process(
                target=worker_entry,
                args=(job.request, job.process_events),
                daemon=True,
            )
            job.status = "running"
            job.updated_at = utc_now()
            try:
                job.process.start()
            except BaseException as exc:
                self._finish(job, "failed", error=f"worker could not start: {exc}")
                job.publish({"type": "failed", "error": job.error})
                job.done.set()
                raise RuntimeError(job.error) from exc
            job.monitor_thread = threading.Thread(
                target=self._monitor,
                args=(job,),
                name=f"mortalsim-job-{job.run_id}",
                daemon=True,
            )
            job.monitor_thread.start()
            self._persist(job)
            return job

    def _monitor(self, job: Job) -> None:
        while True:
            try:
                event = job.process_events.get(timeout=0.2)
            except queue.Empty:
                if job.process is not None and not job.process.is_alive():
                    if job.status == "running":
                        self._finish(job, "failed", error="worker exited without a result")
                        job.publish({"type": "failed", "error": job.error or "worker exited without a result"})
                        job.done.set()
                    return
                continue
            self._handle_event(job, event)
            if event.get("type") in {"completed", "failed"}:
                return

    def _handle_event(self, job: Job, event: dict[str, Any]) -> None:
        event = {"at": utc_now().isoformat(), **event}
        kind = event.get("type")
        if kind == "completed":
            self._finish(job, "completed", result=event.get("result"))
            event = {"type": "completed", "result": job.result}
        elif kind == "failed":
            self._finish(job, "failed", error=event.get("error", "simulation failed"))
        job.publish(event)
        if kind in {"completed", "failed"}:
            job.done.set()

    def _finish(
        self,
        job: Job,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if job.gpu_monitor is not None:
            job.gpu_monitor.stop()
            job.gpu_summary = job.gpu_monitor.summary()
            job.gpu_monitor = None
        if result is not None:
            raw_result = dict(result)
            result = StatisticsService.envelope(
                run_id=job.run_id,
                created_at=job.created_at,
                config=job.request,
                raw_result=raw_result,
                gpu_telemetry=job.gpu_summary,
            )
        job.status = status
        job.result = result
        job.error = error
        job.updated_at = utc_now()
        self._persist(job)

    def cancel(self, run_id: UUID) -> Job:
        job = self.get(run_id)
        if job.status not in {"queued", "running"}:
            return job
        if job.process is not None and job.process.is_alive():
            job.process.terminate()
            job.process.join(timeout=3)
        self._finish(job, "cancelled", error="cancelled by user")
        job.publish({"type": "cancelled", "at": utc_now().isoformat()})
        job.done.set()
        return job

    def get(self, run_id: UUID) -> Job:
        with self.lock:
            try:
                return self.jobs[run_id]
            except KeyError as exc:
                raise KeyError(str(run_id)) from exc

    def list(self) -> list[Job]:
        with self.lock:
            return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    def delete(self, run_id: UUID) -> None:
        job = self.get(run_id)
        if job.status in {"queued", "running"}:
            raise RuntimeError("cannot delete an active run")
        self.jobs.pop(run_id, None)
        path = self.runs_dir / f"{run_id}.json"
        path.unlink(missing_ok=True)

    def _persist(self, job: Job) -> None:
        payload = {
            "schema_version": 1,
            "run_id": str(job.run_id),
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "request": job.request,
            "result": job.result,
            "error": job.error,
        }
        path = self.runs_dir / f"{job.run_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def record(self, job: Job) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "run_id": str(job.run_id),
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "request": job.request,
            "result": job.result,
            "error": job.error,
        }

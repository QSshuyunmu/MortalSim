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
from mortal_app.service import merge_results
from mortal_app.model_registry import ModelRegistry


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
    diagnostic_log: str | None = None
    extension_of: UUID | None = None
    progress: dict[str, Any] = field(default_factory=dict)
    gpu_status: dict[str, Any] | None = None

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
    except BaseException as exc:
        # The parent persists the full traceback locally.  Keep the event
        # concise enough for the UI while still identifying the real failure.
        detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        events.put({
            "type": "failed",
            "error": f"{type(exc).__name__}: {detail}",
            "traceback": traceback.format_exc(),
        })


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
                    status = "interrupted"
                    payload["error"] = "application restarted before the run completed"
                self.jobs[run_id] = Job(
                    run_id=run_id,
                    request=payload.get("request", {}),
                    created_at=created_at,
                    status=status,
                    updated_at=updated_at,
                    result=payload.get("result"),
                    error=payload.get("error"),
                    diagnostic_log=payload.get("diagnostic_log"),
                    extension_of=UUID(payload["extension_of"]) if payload.get("extension_of") else None,
                )
                if status not in {"queued", "running"}:
                    self.jobs[run_id].done.set()
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue

    def create(self, request: RunRequest) -> Job:
        # Do not persist the deprecated legacy first_tsumo field for new
        # 14-tile requests. Existing history records retain it verbatim.
        return self._create_job(request.model_dump(exclude_none=True))

    def _create_job(self, request: dict[str, Any], extension_of: UUID | None = None) -> Job:
        with self.lock:
            active = [job for job in self.jobs.values() if job.status in {"queued", "running"}]
            if active:
                raise RuntimeError("only one simulation can run at a time")
            job = Job(run_id=uuid4(), request=request, extension_of=extension_of)
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

    def create_extension(self, run_id: UUID, additional_runs: int, batch_size: int | None = None) -> Job:
        parent = self.get(run_id)
        if parent.status != "completed" or not parent.result:
            raise RuntimeError("only completed analyses can be extended")
        if int(parent.result.get("schema_version", 0)) != 3:
            raise RuntimeError("schema v1/v2 analyses are read-only; rerun them as Formal Lite before extending")
        if int(parent.result.get("metrics_version", 0)) != 2:
            raise RuntimeError("the analysis metrics version is not extendable")
        if any(job.extension_of == run_id and job.status in {"queued", "running"} for job in self.jobs.values()):
            raise RuntimeError("this analysis already has an active extension")
        request = dict(parent.request)
        contract = parent.result.get("decision_contract")
        if contract != "stable_advantage_v2":
            raise RuntimeError("only stable_advantage_v2 analyses can be extended in Formal Lite")
        if request.get("decision_contract") != contract:
            raise RuntimeError("analysis request and result decision contracts do not match")
        parent_runtime = parent.result.get("runtime") or {}
        required_runtime = (
            "engine_id",
            "artifact_sha256",
            "build_id",
            "compute_capability",
            "batch_size",
            "batch_capacity",
            "precision_profile",
        )
        if any(parent_runtime.get(key) is None for key in required_runtime):
            raise RuntimeError("analysis does not contain a complete Formal Lite runtime identity")
        model = ModelRegistry(self.data_dir).get(request.get("model_id"))
        expected_hash = (parent.result.get("model") or {}).get("sha256")
        if expected_hash and str(expected_hash).lower() != str(model["sha256"]).lower():
            raise RuntimeError("扩容模型与原分析不一致，请保留原模型文件")
        total_before = int(parent.result.get("total_runs", parent.result.get("runs", request.get("runs", 0))))
        parent_batch = int(request.get("batch_size", 1000))
        if parent_batch != 1000 or int(parent_runtime.get("batch_size", 0)) != 1000:
            raise RuntimeError("Formal Lite extensions require the original fixed batch_size=1000")
        if batch_size is not None and int(batch_size) != parent_batch:
            # CUDA AMP can choose different convolution kernels for a different
            # batch shape. That occasionally changes a near-tied argmax, which
            # is unacceptable for an atomic strict-seed extension.
            raise RuntimeError("当前 CUDA AMP 下 Batch 会改变少数逐局动作；严格扩容必须继承原 Batch")
        request["runs"] = int(additional_runs)
        request["batch_size"] = parent_batch
        request["seed"] = int(parent.result.get("seed", request.get("seed", 0))) + total_before
        request["extension_of"] = str(run_id)
        return self._create_job(request, extension_of=run_id)

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
        if kind == "batch_completed":
            job.progress = {key: event[key] for key in ("discard", "completed", "total") if key in event}
        elif kind == "gpu_status":
            job.gpu_status = event
        if kind == "completed":
            try:
                self._finish(job, "completed", result=event.get("result"))
                event = {"type": "completed", "result": job.result}
            except BaseException as exc:
                kind = "failed"
                self._finish(job, "failed", error=f"extension merge failed: {exc}")
                event = {"type": "failed", "error": job.error}
        elif kind == "failed":
            diagnostic_log = self._record_worker_traceback(job, event.get("traceback"))
            if diagnostic_log:
                job.diagnostic_log = diagnostic_log
                event["diagnostic_log"] = diagnostic_log
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
            if job.extension_of is not None:
                parent = self.get(job.extension_of)
                if parent.result is None:
                    raise RuntimeError("extension parent has no result")
                parent.result = merge_results(parent.result, result, str(job.run_id))
                parent.updated_at = utc_now()
                self._persist(parent)
                result = parent.result
        job.status = status
        job.result = result
        job.error = error
        job.updated_at = utc_now()
        self._persist(job)

    def _record_worker_traceback(self, job: Job, worker_traceback: Any) -> str | None:
        if not isinstance(worker_traceback, str) or not worker_traceback.strip():
            return None
        filename = f"worker-{job.run_id}.log"
        path = self.logs_dir / filename
        try:
            path.write_text(
                f"MortalSim worker failure\nrun_id: {job.run_id}\nrecorded_at: {utc_now().isoformat()}\n\n"
                f"{worker_traceback}",
                encoding="utf-8",
            )
        except OSError:
            return None
        return filename

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
            return sorted(
                (job for job in self.jobs.values() if job.extension_of is None),
                key=lambda job: job.created_at,
                reverse=True,
            )

    def active_tasks(self) -> list[dict[str, Any]]:
        with self.lock:
            return [self.task_record(job) for job in self.jobs.values() if job.status in {"queued", "running"}]

    def delete(self, run_id: UUID) -> None:
        job = self.get(run_id)
        if job.status in {"queued", "running"}:
            raise RuntimeError("cannot delete an active run")
        self.jobs.pop(run_id, None)
        path = self.runs_dir / f"{run_id}.json"
        path.unlink(missing_ok=True)

    def _persist(self, job: Job) -> None:
        payload = {
            "schema_version": 3,
            "run_id": str(job.run_id),
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "request": job.request,
            "result": job.result,
            "error": job.error,
            "diagnostic_log": job.diagnostic_log,
            "extension_of": str(job.extension_of) if job.extension_of else None,
        }
        path = self.runs_dir / f"{job.run_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def record(self, job: Job) -> dict[str, Any]:
        return {
            "schema_version": 3,
            "run_id": str(job.run_id),
            "status": job.status,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "request": job.request,
            "result": job.result,
            "error": job.error,
            "diagnostic_log": job.diagnostic_log,
            "extension_of": str(job.extension_of) if job.extension_of else None,
        }

    def task_record(self, job: Job) -> dict[str, Any]:
        return {
            "run_id": str(job.run_id),
            "status": job.status,
            "extension_of": str(job.extension_of) if job.extension_of else None,
            "request": job.request,
            "progress": job.progress,
            "gpu_status": job.gpu_status,
            "created_at": job.created_at.isoformat(),
        }

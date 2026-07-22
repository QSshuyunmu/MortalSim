from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient

import apps.api.main as main_module
from apps.api.job_manager import Job, JobManager
from apps.api.main import app
from apps.api.models import RunRequest


def test_health_and_capabilities_contract() -> None:
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
        capabilities = client.get("/api/capabilities")
        assert capabilities.status_code == 200
        payload = capabilities.json()
        assert payload["cuda_required"] is True
        assert "cuda_error" in payload


def test_run_request_accepts_public_payload() -> None:
    request = RunRequest(
        hand="4567m3477p13406s",
        first_tsumo="6s",
        dora="9s",
        discards=["1s", "6s"],
        runs=100,
        seed=42,
        oya=0,
        batch_size=100,
        rayon_threads=4,
        engine="python",
    )
    assert request.model_dump()["strict_comparison"] is True


def test_gpu_only_runtime_rejects_cpu(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "require_cuda", lambda: (_ for _ in ()).throw(RuntimeError("CUDA unavailable")))
    payload = {
        "hand": "4567m3477p13406s",
        "first_tsumo": "6s",
        "dora": "9s",
        "discards": ["1s"],
    }
    with TestClient(app) as client:
        response = client.post("/api/runs", json=payload)
    assert response.status_code == 503
    assert "CUDA unavailable" in response.json()["detail"]


def test_completed_run_metadata_survives_manager_restart() -> None:
    with TemporaryDirectory() as directory:
        first = JobManager(data_dir=Path(directory))
        job = Job(run_id=uuid4(), request={"discards": ["1s"]}, status="completed")
        job.result = {"schema_version": 1, "candidates": []}
        first.jobs[job.run_id] = job
        first._persist(job)

        second = JobManager(data_dir=Path(directory))
        restored = second.get(job.run_id)
        assert restored.status == "completed"
        assert restored.result == job.result


def test_result_exports(monkeypatch) -> None:
    with TemporaryDirectory() as directory:
        manager = JobManager(data_dir=Path(directory))
        job = Job(run_id=uuid4(), request={"discards": ["1s"]}, status="completed")
        job.result = {
            "run_id": str(job.run_id),
            "summaries": [{"discard": "1s", "games": 1, "avg_point": 100, "avg_rank": 2.0}],
        }
        manager.jobs[job.run_id] = job
        monkeypatch.setattr(main_module, "manager", manager)
        with TestClient(main_module.app) as client:
            response = client.get(f"/api/runs/{job.run_id}/export?format=csv")
        assert response.status_code == 200
        assert "discard,games" in response.text

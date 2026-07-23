from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import AsyncIterator
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mortal_app.service import LIBRIICHI_DIR, MODEL_PATH, candidate_identity, cuda_diagnostics, require_cuda
from mortal_app.model_registry import ModelRegistry

from .job_manager import JobManager
from .models import CapabilityResponse, ExtensionRequest, ReplayRequest, RunRequest
from .exports import build_html, build_xlsx


ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = ROOT / "apps" / "web" / "dist"
MODEL_MANIFEST = ROOT / "models" / "MODEL_MANIFEST.json"

app = FastAPI(title="MortalSim Local API", version="0.2.0-alpha.0")
manager = JobManager()
models_registry = ModelRegistry(manager.data_dir)


def _sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": app.version}


@app.get("/api/capabilities", response_model=CapabilityResponse)
def capabilities() -> CapabilityResponse:
    cuda = cuda_diagnostics()
    return CapabilityResponse(
        platform=platform.platform(),
        python=sys.version.split()[0],
        cuda_available=bool(cuda["available"]),
        cuda_required=True,
        torch_version=cuda["torch_version"],
        cuda_version=cuda["cuda_version"],
        gpu_name=cuda["gpu_name"],
        cuda_error=cuda["error"],
        nvidia_smi_available=shutil.which("nvidia-smi") is not None,
        model_exists=MODEL_PATH.exists(),
        model_path=str(MODEL_PATH),
        libriichi_exists=(LIBRIICHI_DIR / "libriichi.cp313-win_amd64.pyd").exists()
        or (LIBRIICHI_DIR / "libriichi.dll").exists(),
        recommended_engine="python",
        data_dir=str(manager.data_dir),
    )


@app.get("/api/models")
def models() -> list[dict[str, object]]:
    return models_registry.list()


@app.post("/api/models/import", status_code=201)
async def import_model(request: Request, filename: str = Query(..., min_length=1, max_length=255)) -> dict[str, object]:
    import hashlib

    temporary = models_registry.root / f".api-{os.getpid()}-{Path(filename).name}.upload"
    try:
        require_cuda()
        written, digest = 0, hashlib.sha256()
        with temporary.open("xb") as destination:
            async for chunk in request.stream():
                written += len(chunk)
                if written > 2 * 1024 * 1024 * 1024:
                    raise ValueError("模型文件超过 2 GiB 限制")
                digest.update(chunk)
                destination.write(chunk)
        entry = models_registry.register_staged(temporary, filename, digest.hexdigest(), written)
        return entry
    except (RuntimeError, ValueError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        temporary.unlink(missing_ok=True)


@app.post("/api/runs", status_code=202)
def create_run(request: RunRequest) -> dict[str, object]:
    try:
        require_cuda()
        models_registry.get(request.model_id)
        job = manager.create(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"run_id": str(job.run_id), "status": job.status}


@app.get("/api/runs")
def list_runs() -> list[dict[str, object]]:
    return [manager.record(job) for job in manager.list()]


@app.get("/api/tasks/active")
def active_tasks() -> list[dict[str, object]]:
    return manager.active_tasks()


@app.get("/api/runs/{run_id}")
def get_run(run_id: UUID) -> dict[str, object]:
    try:
        return manager.record(manager.get(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc


@app.get("/api/runs/{run_id}/result")
def get_result(run_id: UUID) -> JSONResponse:
    try:
        job = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if job.result is None:
        raise HTTPException(status_code=409, detail=f"run status: {job.status}")
    return JSONResponse(job.result)


@app.get("/api/runs/{run_id}/samples")
def get_samples(run_id: UUID, candidate: str, metric: str) -> dict[str, object]:
    try:
        job = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if job.result is None:
        raise HTTPException(status_code=409, detail=f"run status: {job.status}")
    candidates = job.result.get("candidates", [])
    summary = next((item for item in candidates if candidate_identity(item) == candidate), None)
    # Schema-v1 and early schema-v2 results only identify a candidate by tile.
    # Keep that query form working only when it remains unambiguous.
    if summary is None:
        matches = [item for item in candidates if item.get("discard") == candidate]
        summary = matches[0] if len(matches) == 1 else None
    if summary is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    items = summary.get("samples", {}).get(metric, [])
    return {"candidate": candidate, "metric": metric, "samples": items, "total": len(items)}


@app.post("/api/runs/{run_id}/replay", status_code=202)
def replay_sample(run_id: UUID, replay: ReplayRequest) -> dict[str, object]:
    try:
        original = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    source_candidates = original.request.get("discards", [])
    selected = next(
        (item for item in source_candidates if candidate_identity(item) == replay.candidate),
        None,
    )
    if selected is None:
        legacy_matches = [item for item in source_candidates if isinstance(item, str) and item == replay.candidate]
        selected = legacy_matches[0] if len(legacy_matches) == 1 else None
    if selected is None:
        raise HTTPException(status_code=400, detail="candidate does not belong to the original run")
    seed = replay.seed[0] if isinstance(replay.seed, list) else replay.seed
    original_request = dict(original.request)
    legacy_oya = int(original_request.pop("oya", 0))
    original_request.setdefault("round", f"E{legacy_oya + 1}")
    request = RunRequest(**{
        **original_request,
        "discards": [selected],
        "runs": 1,
        "batch_size": 1,
        "seed": seed,
        "replay_of": run_id,
        "expected_trace_hash": replay.expected_trace_hash,
    })
    try:
        require_cuda()
        job = manager.create(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": str(job.run_id), "status": job.status, "replay_of": str(run_id)}


@app.post("/api/runs/{run_id}/extensions", status_code=202)
def extend_run(run_id: UUID, extension: ExtensionRequest) -> dict[str, object]:
    try:
        require_cuda()
        parent = manager.get(run_id)
        total_before = int((parent.result or {}).get("total_runs", (parent.result or {}).get("runs", 0)))
        operation = manager.create_extension(run_id, extension.additional_runs, extension.batch_size)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "run_id": str(run_id),
        "operation_id": str(operation.run_id),
        "status": operation.status,
        "total_before": total_before,
        "total_after": total_before + extension.additional_runs,
        "seed_start": operation.request["seed"],
        "seed_end": operation.request["seed"] + extension.additional_runs - 1,
        "batch_size": operation.request["batch_size"],
    }


@app.get("/api/runs/{run_id}/extensions/{operation_id}/events")
async def extension_events(run_id: UUID, operation_id: UUID, since: int = Query(default=0, ge=0)) -> StreamingResponse:
    try:
        operation = manager.get(operation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="extension not found") from exc
    if operation.extension_of != run_id:
        raise HTTPException(status_code=404, detail="extension not found")
    return StreamingResponse(
        event_stream(operation_id, since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/runs/{run_id}/extensions/{operation_id}/cancel")
def cancel_extension(run_id: UUID, operation_id: UUID) -> dict[str, object]:
    try:
        operation = manager.get(operation_id)
        if operation.extension_of != run_id:
            raise KeyError(str(operation_id))
        manager.cancel(operation_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="extension not found") from exc
    return {"run_id": str(run_id), "operation_id": str(operation_id), "status": operation.status}


@app.get("/api/runs/{run_id}/export")
def export_result(run_id: UUID, format: str = Query(default="full", pattern="^(full|json|xlsx|csv|html)$")):
    """Return a portable report without exposing internal worker objects.

    ``full`` is the user-facing export: the complete persisted schema, including
    configuration, comparisons, metric details, extension history, and retained
    representative samples. Excel contains only the complete user-facing
    metric table; HTML is the offline report. CSV remains a compatibility
    format but is not advertised in the web UI.
    """
    try:
        job = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if job.result is None:
        raise HTTPException(status_code=409, detail=f"run status: {job.status}")

    import csv
    import io
    import json

    filename = f"mortalsim-{run_id}"
    if format in {"full", "json"}:
        return PlainTextResponse(
            json.dumps(job.result, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}{"-full" if format == "full" else ""}.json"'},
        )
    if format == "xlsx":
        return Response(
            content=build_xlsx(job.result),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'},
        )
    candidates = job.result.get("candidates") or job.result.get("summaries", [])
    if format == "csv":
        output = io.StringIO()
        def flatten(prefix: str, value: object, row: dict[str, object]) -> None:
            if isinstance(value, dict):
                for key, child in value.items():
                    if key not in {"samples", "yaku"}:
                        flatten(f"{prefix}.{key}" if prefix else key, child, row)
            elif not isinstance(value, list):
                row[prefix] = value

        flat_rows: list[dict[str, object]] = []
        for candidate in candidates:
            row: dict[str, object] = {}
            flatten("", candidate, row)
            for yaku in candidate.get("yaku", []):
                for key in ("count", "rate", "total_tiles"):
                    row[f"yaku.{yaku['id']}.{key}"] = yaku.get(key)
            flat_rows.append(row)
        priority = {"discard": 0, "games": 1, "completed_games": 2, "errors": 3}
        columns = sorted({key for row in flat_rows for key in row}, key=lambda key: (priority.get(key, 10), key))
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flat_rows)
        return PlainTextResponse(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    return PlainTextResponse(
        build_html(job.result, str(run_id)),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="{filename}.html"'},
    )


@app.post("/api/runs/{run_id}/cancel")
def cancel_run(run_id: UUID) -> dict[str, object]:
    try:
        job = manager.cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    return {"run_id": str(run_id), "status": job.status}


@app.delete("/api/runs/{run_id}", status_code=204)
def delete_run(run_id: UUID) -> None:
    try:
        manager.delete(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


async def event_stream(run_id: UUID, since: int) -> AsyncIterator[str]:
    try:
        job = manager.get(run_id)
    except KeyError:
        yield "event: failed\ndata: {\"error\":\"run not found\"}\n\n"
        return
    index = max(0, since)
    while True:
        with job.event_condition:
            events = job.event_log[index:]
            index += len(events)
            done = job.done.is_set() and index >= len(job.event_log)
        for event in events:
            kind = event.get("type", "message")
            import json

            yield f"event: {kind}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        if done:
            return
        await asyncio.sleep(0.2)


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: UUID, since: int = Query(default=0, ge=0)) -> StreamingResponse:
    return StreamingResponse(
        event_stream(run_id, since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if WEB_DIST.exists() and (WEB_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")


@app.get("/{path:path}")
def frontend(path: str):
    if not WEB_DIST.exists():
        return JSONResponse({"message": "Web frontend is not built", "api": "/api/health"})
    candidate = (WEB_DIST / path).resolve()
    if candidate.is_file() and str(candidate).startswith(str(WEB_DIST.resolve())):
        return FileResponse(candidate)
    return FileResponse(WEB_DIST / "index.html")


def main() -> None:
    import uvicorn

    uvicorn.run("apps.api.main:app", host="127.0.0.1", port=int(os.environ.get("MORTALSIM_PORT", "0")), reload=False)


if __name__ == "__main__":
    main()

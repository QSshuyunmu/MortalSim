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

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mortal_app.service import LIBRIICHI_DIR, MODEL_PATH

from .job_manager import JobManager
from .models import CapabilityResponse, RunRequest


ROOT = Path(__file__).resolve().parents[2]
WEB_DIST = ROOT / "apps" / "web" / "dist"
MODEL_MANIFEST = ROOT / "models" / "MODEL_MANIFEST.json"

app = FastAPI(title="MortalSim Local API", version="0.1.0-alpha")
manager = JobManager()


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
    cuda = False
    try:
        import torch

        cuda = bool(torch.cuda.is_available())
    except Exception:
        pass
    return CapabilityResponse(
        platform=platform.platform(),
        python=sys.version.split()[0],
        cuda_available=cuda,
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
    manifest_hash = None
    if MODEL_MANIFEST.exists():
        try:
            import json

            manifest_hash = json.loads(MODEL_MANIFEST.read_text(encoding="utf-8"))["models"][0]["sha256"]
        except (OSError, KeyError, IndexError, TypeError, ValueError):
            manifest_hash = None
    actual_hash = _sha256(MODEL_PATH)
    return [{
        "id": "mortal-v4-20240308",
        "path": str(MODEL_PATH),
        "exists": MODEL_PATH.exists(),
        "size_bytes": MODEL_PATH.stat().st_size if MODEL_PATH.exists() else None,
        "sha256": actual_hash,
        "integrity_ok": bool(actual_hash and manifest_hash and actual_hash.lower() == manifest_hash.lower()),
        "engine": "python-amp",
        "experimental": False,
    }]


@app.post("/api/runs", status_code=202)
def create_run(request: RunRequest) -> dict[str, object]:
    try:
        job = manager.create(request)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": str(job.run_id), "status": job.status}


@app.get("/api/runs")
def list_runs() -> list[dict[str, object]]:
    return [manager.record(job) for job in manager.list()]


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


@app.get("/api/runs/{run_id}/export")
def export_result(run_id: UUID, format: str = Query(default="json", pattern="^(json|csv|html)$")):
    """Return a portable report without exposing internal worker objects."""
    try:
        job = manager.get(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="run not found") from exc
    if job.result is None:
        raise HTTPException(status_code=409, detail=f"run status: {job.status}")

    import csv
    import io
    import json
    from html import escape

    filename = f"mortalsim-{run_id}"
    if format == "json":
        return PlainTextResponse(
            json.dumps(job.result, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}.json"'},
        )
    summaries = job.result.get("summaries", [])
    if format == "csv":
        output = io.StringIO()
        columns = ["discard", "games", "errors", "avg_point", "avg_rank", "agari_rate", "houjuu_rate", "riichi_rate", "fuuro_rate"]
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summaries)
        return PlainTextResponse(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
        )
    rows = "".join(
        "<tr>" + "".join(f"<td>{escape(str(summary.get(column, '')))}</td>" for column in ("discard", "games", "avg_point", "avg_rank", "agari_rate", "houjuu_rate")) + "</tr>"
        for summary in summaries
    )
    html = f"""<!doctype html><meta charset='utf-8'><title>MortalSim {escape(str(run_id))}</title>
<style>body{{font:14px system-ui;max-width:960px;margin:40px auto;color:#1d282d}} table{{border-collapse:collapse;width:100%}}th,td{{padding:8px;border-bottom:1px solid #ddd;text-align:right}}th:first-child,td:first-child{{text-align:left}}</style>
<h1>MortalSim result</h1><p>Run {escape(str(run_id))}</p>
<table><thead><tr><th>Discard</th><th>Games</th><th>Average point</th><th>Average rank</th><th>Agari rate</th><th>Houjuu rate</th></tr></thead><tbody>{rows}</tbody></table>"""
    return PlainTextResponse(
        html,
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

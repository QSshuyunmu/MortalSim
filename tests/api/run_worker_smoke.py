"""Manual Windows worker smoke test; run as a file, not through stdin."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

from apps.api.job_manager import JobManager
from apps.api.models import RunRequest
from mortal_app.service import MODEL_PATH


def main() -> int:
    if not MODEL_PATH.exists():
        print(f"SKIPPED: model not present at {MODEL_PATH}")
        return 0
    data_dir = Path(tempfile.mkdtemp(prefix="mortalsim-smoke-"))
    os.environ["MORTALSIM_DATA_DIR"] = str(data_dir)
    manager = JobManager(data_dir)
    request = RunRequest(
        hand="4567m3477p13406s",
        first_tsumo="6s",
        dora="9s",
        discards=["1s"],
        runs=1,
        seed=42,
        oya=0,
        batch_size=1,
        rayon_threads=1,
    )
    job = manager.create(request)
    deadline = time.time() + 120
    while not job.done.wait(0.5):
        if time.time() > deadline:
            manager.cancel(job.run_id)
            raise TimeoutError("worker smoke test timed out")
    print(f"status={job.status} error={job.error!r} events={[event.get('type') for event in job.event_log]}")
    return 0 if job.status == "completed" and job.result else 1


if __name__ == "__main__":
    raise SystemExit(main())

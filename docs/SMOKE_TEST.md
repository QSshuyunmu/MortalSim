# Worker Smoke Test

With the application dependencies and model installed, run this from the
repository root:

```powershell
python -m tests.api.run_worker_smoke
```

The test uses one fixed-seed game and verifies multiprocessing startup,
model loading, Rust runner execution, event delivery and versioned result
creation. It writes temporary data outside the repository.

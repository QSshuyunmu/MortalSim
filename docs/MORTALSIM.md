# MortalSim Application

MortalSim is the local web front end for the Mortal first-discard simulator.
The development entry point is:

```powershell
python run_mortalsim.py
```

It starts a FastAPI service on a random loopback port, opens the browser, and
keeps simulation work in a separate process. Results are stored under
`%LOCALAPPDATA%\\MortalSim` (or `MORTALSIM_DATA_DIR` when set), never in the
source or installation directory.

The current MVP supports fixed-seed candidate comparison, live progress and
GPU telemetry, result persistence, history reopening, diagnostics, and JSON,
CSV, or self-contained HTML exports. A manual one-game worker smoke test is
available with `python -m tests.api.run_worker_smoke`.

The Python AMP engine is the only production engine in this release; ONNX
remains experimental until strict per-seed action equivalence is demonstrated.

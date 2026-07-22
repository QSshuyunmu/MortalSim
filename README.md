# MortalSim

MortalSim is a local Windows web desktop application for comparing Mortal
first-discard simulations. It runs the existing Rust `libriichi` runner and
Python AMP model locally; hand data, seeds, telemetry and results are not
uploaded.

## Quick Start

Download the CUDA Portable ZIP from GitHub Releases, extract it, and
double-click `MortalSim.exe`. MortalSim is GPU-only: an NVIDIA GPU, a current
driver, and CUDA-enabled PyTorch are required. The app listens on `127.0.0.1`
and opens the browser automatically.

For development:

```powershell
python -m pip install -r requirements-cuda.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
python run_mortalsim.py
```

The model weight is intentionally not committed until redistribution rights
are confirmed. Place the authorized v4 weight at
`Akagi/model_v4_20240308_best_min.pth`; see `MODEL_LICENSE.md` and
`models/MODEL_MANIFEST.json`.

## Status

The Python AMP engine is production-facing. ONNX remains experimental until
strict per-seed action equivalence is proven. See `docs/INSTALL.md`,
`docs/USER_GUIDE.md` and `docs/SMOKE_TEST.md`.

## License

Application code is AGPL-3.0-or-later. Dependencies, model weights and CUDA
runtime components may have separate terms; see `NOTICE`,
`THIRD_PARTY_LICENSES.md` and `MODEL_LICENSE.md`.

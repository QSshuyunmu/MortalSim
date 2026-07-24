# MortalSim

<p align="center">
  <img src="apps/web/public/mascot.webp" alt="MortalSim red crab mascot holding a mahjong tile" width="160">
</p>

MortalSim is a local Windows web desktop application for comparing Mortal
first-discard simulations. It runs the existing Rust `libriichi` runner and
Python AMP model locally; hand data, seeds, telemetry and results are not
uploaded.

It is an offline analysis tool. It does not connect to a mahjong game client,
intercept network traffic, or automate live play. The current user interface
is Simplified Chinese.

## Features

- Fixed-seed comparison of multiple first-discard candidates
- NAGA-compatible average round-balance statistics with confidence intervals
- Five mutually exclusive terminal outcomes and detailed win, defense,
  riichi, tenpai, call, and yaku metrics
- Background history extension, cancellation, replay, and GPU telemetry
- Local model library with SHA-256 identity and CUDA compatibility checks
- Excel, JSON, and self-contained HTML exports

## Quick Start

Download the matching `Core` archive and every `Runtime-XX` archive from one
GitHub Release. Extract all of them into the same folder, then double-click
`Start-MortalSim.cmd`. MortalSim is GPU-only: an NVIDIA GPU, a current driver,
and the bundled CUDA-enabled PyTorch runtime are required. The app listens on
`127.0.0.1` and opens the browser automatically.

MortalSim never ships or downloads a model checkpoint. After the app opens,
import a local compatible Mortal `.pth` file from **Settings and
Diagnostics**. The model remains in the local application data directory;
MortalSim does not upload it. See `MODEL_LICENSE.md`.

For development:

```powershell
python -m pip install -r requirements-lock.txt
python -m pip install -r requirements-test.txt
npm --prefix apps/web ci
npm --prefix apps/web run build
python run_mortalsim.py
```

Model weights are intentionally not committed. For local development, a
compatible v4 checkpoint may be placed at
`models/model_v4_20240308_best_min.pth`; public builds still exclude it.

Run the source checks with:

```powershell
python -m pytest tests mortal_app/test_gpu_monitor.py -q
cargo test -p libriichi --lib
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

## Status

`v0.2.0-alpha.0` is a prerelease. The Python AMP engine is production-facing.
ONNX remains experimental until strict per-seed action equivalence is proven.
See `docs/INSTALL.md`,
`docs/USER_GUIDE.md` and `docs/SMOKE_TEST.md`.

## License

Application code is AGPL-3.0-or-later. Dependencies, model weights and CUDA
runtime components may have separate terms; see `NOTICE`,
`THIRD_PARTY_LICENSES.md` and `MODEL_LICENSE.md`.

# MortalSim v0.2.0-alpha.0

This is the first public prerelease of the local MortalSim desktop
application.

## Supported platform

- Windows 10 or 11 x64
- NVIDIA GPU with a driver compatible with the bundled CUDA 12.4 runtime
- Approximately 500 MiB of free disk space for the extracted application and
  local cache

MortalSim is GPU-only. It does not fall back to CPU inference.

## Installation

Download `MortalSim-Windows-x64-Lite-v0.2.0a0.zip`, extract it into a normal
folder, then run `Start-MortalSim.cmd`.

The release does not contain or download model weights. Import a compatible
local Mortal `.pth` file from Settings and Diagnostics after startup.

To uninstall, close MortalSim, delete the extracted application directory,
and optionally delete `%LOCALAPPDATA%\MortalSim` to remove models, history,
logs, and settings.

## Included

- Fixed-seed first-discard comparison using the Rust simulation core
- NAGA-compatible average round-balance statistics
- Five terminal outcome categories and detailed riichi, tenpai, call, defense,
  and yaku statistics
- Background history extension with atomic merge and cancellation
- Local model import with SHA-256 identity and CUDA self-test
- GPU telemetry and persistent local history
- Excel statistical-table, complete JSON, and offline HTML exports

## Correctness status

- The Lite native CUDA graph is the selectable compact inference path. Its
  strict action/trace equivalence gate against PyTorch AMP is still open; use
  the fixed-seed validation record before treating results as interchangeable
  with the reference engine.
- The headline average round balance uses terminal Hora/Ryukyoku settlements;
  accepted-riichi payments are verified internally but are not exposed as a
  second point metric.
- Fixed-seed Rust and application regression tests are included in CI.
- ONNX inference remains experimental and is not selectable in the public UI.

## Known limitations

- The interface is currently Simplified Chinese.
- A compatible user-provided model is required.
- CUDA AMP can diverge on rare borderline actions when Batch shape changes.
  History extension therefore inherits the original Batch.
- Full hanchan placement and rating-point projections are not included.

## Integrity and licenses

Verify the downloaded archive against `SHA256SUMS-Lite.txt`. The ZIP contains
the release manifest, AGPL license, notices, model distribution policy,
installation guide, validation record and troubleshooting guide.

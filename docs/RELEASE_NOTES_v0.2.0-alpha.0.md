# MortalSim v0.2.0-alpha.0

This is the first public prerelease of the local MortalSim desktop
application.

## Supported platform

- Windows 10 or 11 x64
- NVIDIA GPU with a driver compatible with the bundled CUDA 12.4 runtime
- Approximately 4 GiB of free disk space for the extracted application

MortalSim is GPU-only. It does not fall back to CPU inference.

## Installation

Download the `Core` ZIP and all `Runtime-XX` ZIP files for this version.
Extract every archive into the same directory, then run
`Start-MortalSim.cmd`.

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

- Python AMP is the production inference path.
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

Verify every downloaded archive against `SHA256SUMS.txt`. The Core archive
contains `SBOM.cdx.json`, the release manifest, AGPL license, notices, model
distribution policy, installation guide, and troubleshooting guide.

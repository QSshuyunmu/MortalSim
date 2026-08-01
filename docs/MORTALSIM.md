# MortalSim Application

MortalSim is a loopback-only FastAPI and React desktop application around the
Rust `libriichi::arena::CustomKyokuRunner`. The launcher selects a random local
port, starts simulation workers in separate processes and opens the default
browser. Runtime data is stored under `%LOCALAPPDATA%\MortalSim` or the
explicit `MORTALSIM_DATA_DIR`.

The public v0.3 Lite package is GPU-only, libtorch-free and supports the
versioned `stable_advantage_v2` contract on NVIDIA SM89. It imports a standard
Mortal v4/256/54 checkpoint through a restricted reader, replaces the AOT graph
constants and returns raw advantage scores. Legal-action selection remains in
Rust. The package does not contain or download model weights.

Development-only `legacy_amp_v1` uses PyTorch CUDA autocast and exists solely
for migration experiments. It is not present in the public Portable package,
and its schema v1/v2 results cannot be merged with schema v3.

The application supports fixed-seed candidate comparison, live progress, GPU
telemetry, persistent history, atomic background extension, replay, diagnostics
and JSON/Excel/offline HTML exports. See `DECISION_CONTRACTS.md`,
`RESULT_SCHEMA_V3.md` and `LITE_VALIDATION.md` for the formal contract and open
release Gates.

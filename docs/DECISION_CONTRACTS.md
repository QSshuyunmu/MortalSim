# Decision contracts

## `legacy_amp_v1`

This contract names the historical Python engine: FP32 Mortal parameters,
PyTorch CUDA autocast, masked final Q values, and the historical argmax path.
It remains available only in a development environment that explicitly
installs PyTorch. It is a reference and history label, not part of the Formal
Lite portable archive.

## `stable_advantage_v2`

This is the sole public contract in MortalSim v0.3 Formal Lite:

1. Mortal v4, 256 channels, 54 residual blocks.
2. Static AMP AOTInductor graph compiled for compute capability 8.9.
3. Raw DQN advantage output, converted to float32 at the graph boundary.
4. Public batch 1000 and graph capacity 1024.
5. Zero observation padding and false action-mask padding.
6. Rust legal-action selection in ascending action-ID order.
7. Strict `>` replacement; exact ties retain the smaller action ID.
8. NaN rejection and no-legal-action rejection.
9. The agari guard reuses the selector while excluding action 43.

The authoritative identity is the combination of model SHA256, native runtime
artifact SHA256, build ID, SM89 target, fixed batch/padding rules, and Rust
selector. Any identity difference creates a separate experiment and cannot be
merged into an existing run.

# MortalSim v0.3.0-rc.1

This release candidate introduces the versioned `stable_advantage_v2` decision
contract and schema v3 runtime identity.

## Highlights

- libtorch-free AOTInductor CUDA graph returning raw DQN advantage scores;
- authoritative legal-action selection in Rust with deterministic tie handling;
- fixed public batch 1000 and native graph capacity 1024;
- explicit SM89/RTX 40 compatibility check;
- model, runtime artifact, build, precision, and decision identities persisted;
- old schema v1/v2 records remain readable but are no longer extendable;
- “rerun as Formal Lite” creates a new schema v3 record;
- release archive still contains no model weights.

## RC status

The strict Legacy AMP reproduction gate failed and is documented in
`docs/PARITY_ROOT_CAUSE.md`. This RC intentionally uses a new, stable contract
instead of claiming equivalence. A final v0.3.0 release additionally requires a
second RTX 40 machine and the large migration/stability gates recorded in
`docs/LITE_VALIDATION-v0.3.0-rc.1.json`.

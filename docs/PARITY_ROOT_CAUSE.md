# Lite parity root-cause report

## Decision

Gate A is **failed** for the current `legacy_amp_v1` reproduction attempt. The
formal v0.3 line therefore uses `stable_advantage_v2`; it does not claim bitwise
or per-action equivalence with PyTorch CUDA autocast.

This is a protocol change, not a hidden correction. Schema v3 records the
decision contract, model SHA256, native artifact SHA256, build ID, SM target,
batch size, capacity, and precision profile. Results from different identities
cannot be merged.

## Reproduced evidence

The fixed reference trajectory contains 300 games and 14,397 decisions. The
three runnable native candidates diverged as follows:

| Candidate | Action mismatches | First known positions |
| --- | ---: | --- |
| AMP-static GEMM | 3 | 11519, 12420, 13701 |
| AMP-static native Conv1d | 3 | 4806, 12420, 13701 |
| FP32 graph | 6 | 616, 4806, 6221, 7985, 11519, 11937 |

On the formal first-discard corpus (`4567m3477p134066s`, dora indicator `9s`,
seed `(42, 0xDEAD)`), AMP-static GEMM differs from the reference on 43 of
55,438 decisions after `1s`, and 29 of 56,842 decisions after `6s`.

Changing Conv lowering or promoting the complete graph to FP32 moves the
near-tie divergences rather than removing them. There is no stable majority
vote or action-specific correction that generalizes.

## Autocast AOT attempt

A graph containing real `torch.autocast("cuda")` was captured, but the first
failing Triton kernel requested 131,072 bytes of shared memory on the RTX 4050
Laptop, whose per-block limit is 101,376 bytes. Smaller probe batches and the
ATen/no-autotune variants did not produce a runnable Gate A artifact.

This satisfies the stop condition: no TensorRT/ONNX substitution, action bias,
seed table, or observation hash is used to make the old contract appear to
pass.

## Stable contract

`stable_advantage_v2` exports the v4 DQN's raw 46-action advantage tensor as
float32 at the graph boundary. The graph itself keeps the existing static AMP
profile. Rust selects the first legal action ID and replaces it only when a
strictly greater score is seen. Exact ties therefore resolve to the lower
action ID. NaN scores and empty legal masks are errors. The rule-based agari
guard invokes the same selector with action 43 excluded.

Formal execution is fixed to public batch 1000, graph capacity 1024, zero
observation padding, false mask padding, and an SM89 cubin. The current RC
runtime identity is stored in `packaging/lite_runtime/runtime_manifest.json`
during a release build; native binaries themselves remain release-builder
artifacts and are not committed to the public source repository.

## Remaining release gates

The implementation is an RC until all of the following are attached to the
release validation JSON:

- at least 1,000,000 paired decisions with action-change rate at most 0.10%;
- 50,000 games per candidate with the configured statistical migration bounds;
- three independent-process reproducibility runs;
- 1,000 + 1,000 extension equivalence to one-shot 2,000;
- three compatible local model smoke runs;
- the same corpus on a second Windows RTX 40 (SM89) machine;
- 30-minute VRAM stability and package size gates.

Without the second hardware gate, only `v0.3.0-rc.*` may be published.

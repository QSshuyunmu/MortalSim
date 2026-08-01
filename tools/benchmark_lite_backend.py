#!/usr/bin/env python3
"""Measure DirectML parity and throughput against the PyTorch AMP reference."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
import torch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from export_mortal_onnx import build_policy  # noqa: E402


def median_time(call, repeats: int = 5) -> float:
    call()
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        call()
        samples.append(time.perf_counter() - started)
    return float(np.median(samples))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device-id", type=int, default=0)
    parser.add_argument("--batches", type=int, nargs="+", default=[1, 8, 64, 256, 512])
    args = parser.parse_args()

    if "DmlExecutionProvider" not in ort.get_available_providers():
        raise RuntimeError(f"DirectML provider unavailable: {ort.get_available_providers()}")

    options = ort.SessionOptions()
    options.enable_mem_pattern = False
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(
        str(args.model),
        sess_options=options,
        providers=[("DmlExecutionProvider", {"device_id": args.device_id})],
    )
    policy = build_policy(args.checkpoint).cuda().eval()
    rng = np.random.default_rng(42)
    total = 0
    mismatches = 0
    worst_q = 0.0

    print(f"ORT {ort.__version__}; providers={session.get_providers()}; device_id={args.device_id}")
    print("batch  mismatch  max|dq|  torch_ms  dml_ms  dml_obs/s")
    for batch in args.batches:
        obs = rng.random((batch, 1012, 34), dtype=np.float32)
        mask = rng.random((batch, 46)) > 0.2
        mask[:, 45] = True
        obs_cuda = torch.from_numpy(obs).cuda()
        mask_cuda = torch.from_numpy(mask).cuda()

        def torch_call():
            with torch.inference_mode(), torch.autocast("cuda", enabled=True):
                return policy(obs_cuda, mask_cuda).float().cpu().numpy()

        def dml_call():
            return session.run(["q_values"], {"obs": obs, "mask": mask})[0]

        expected = torch_call()
        actual = dml_call()
        finite = np.isfinite(expected) & np.isfinite(actual)
        max_q = float(np.max(np.abs(expected[finite] - actual[finite])))
        mismatch = int(np.count_nonzero(expected.argmax(-1) != actual.argmax(-1)))
        torch_time = median_time(torch_call)
        dml_time = median_time(dml_call)
        total += batch
        mismatches += mismatch
        worst_q = max(worst_q, max_q)
        print(
            f"{batch:5d}  {mismatch:8d}  {max_q:7.4f}  "
            f"{torch_time * 1000:8.2f}  {dml_time * 1000:6.2f}  {batch / dml_time:9.1f}"
        )

    print(f"TOTAL_ARGMAX={total - mismatches}/{total}; WORST_Q={worst_q:.6g}")
    return 0 if mismatches == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

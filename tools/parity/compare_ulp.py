#!/usr/bin/env python3
"""Compare two layer-probe archives with absolute and ULP diagnostics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


def ordered_bits(values: np.ndarray) -> np.ndarray:
    floats = np.asarray(values, dtype=np.float32)
    signed = floats.view(np.int32).astype(np.int64)
    return np.where(signed < 0, 0x80000000 - signed, signed)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    reference, candidate = np.load(args.reference), np.load(args.candidate)
    report: dict[str, object] = {"layers": {}}
    for key in sorted(set(reference.files) & set(candidate.files) - {"mask"}):
        left = np.asarray(reference[key], dtype=np.float32)
        right = np.asarray(candidate[key], dtype=np.float32)
        if left.shape != right.shape:
            report["layers"][key] = {"shape_mismatch": [left.shape, right.shape]}
            continue
        absolute = np.abs(left - right)
        ulp = np.abs(ordered_bits(left) - ordered_bits(right))
        report["layers"][key] = {
            "shape": left.shape,
            "max_abs": float(np.nanmax(absolute)),
            "mean_abs": float(np.nanmean(absolute)),
            "max_ulp_f32": int(np.nanmax(ulp)),
            "mean_ulp_f32": float(np.nanmean(ulp)),
        }
    if "advantage" in reference.files and "advantage" in candidate.files and "mask" in reference.files:
        mask = reference["mask"].astype(bool)
        ref_action = np.where(mask, reference["advantage"], -np.inf).argmax(axis=1)
        candidate_action = np.where(mask, candidate["advantage"], -np.inf).argmax(axis=1)
        report["action_mismatches"] = int(np.count_nonzero(ref_action != candidate_action))
        sorted_advantage = np.sort(np.where(mask, reference["advantage"], -np.inf), axis=1)
        top2_margin = sorted_advantage[:, -1] - sorted_advantage[:, -2]
        report["reference_top2_margin"] = {
            "min": float(np.min(top2_margin)),
            "median": float(np.median(top2_margin)),
        }
    payload = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

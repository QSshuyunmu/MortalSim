#!/usr/bin/env python3
"""Compare a Legacy AMP decision corpus with the Formal Lite runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "target" / "release"), str(ROOT)]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _chunks(path: Path):
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            yield chunk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-decisions", type=int)
    parser.add_argument("--max-action-change-rate", type=float, default=0.001)
    parser.add_argument("--mismatch-samples", type=int, default=100)
    args = parser.parse_args()

    manifest_path = args.corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("decision_contract") != "legacy_amp_v1":
        raise RuntimeError("corpus is not a legacy_amp_v1 reference corpus")
    files = manifest.get("batch_files") or []
    if not files:
        raise RuntimeError("corpus has no decision batches")
    for item in files:
        path = args.corpus / item["file"]
        if _sha256(path) != item["sha256"]:
            raise RuntimeError(f"corpus hash mismatch: {path.name}")

    os.environ["MORTALSIM_LITE_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    with tempfile.TemporaryDirectory(prefix="mortalsim-runtime-compare-") as temporary:
        data_root = Path(temporary)
        os.environ["MORTALSIM_DATA_DIR"] = str(data_root)
        from mortal_app.model_registry import ModelRegistry
        from mortal_app.service import _load_engine

        imported = ModelRegistry(data_root).import_chunks(
            args.checkpoint.name, _chunks(args.checkpoint), engine="lite"
        )
        engine, _, _ = _load_engine(
            str(imported["id"]), "lite", "stable_advantage_v2"
        )
        decisions = mismatches = 0
        margins: list[float] = []
        examples: list[dict[str, object]] = []
        try:
            for item in files:
                if args.max_decisions is not None and decisions >= args.max_decisions:
                    break
                path = args.corpus / item["file"]
                with np.load(path) as batch:
                    obs = np.asarray(batch["obs"], dtype=np.float32)
                    mask = np.asarray(batch["mask"], dtype=np.bool_)
                    reference = np.asarray(batch["reference_action"], dtype=np.int64)
                remaining = (
                    len(reference)
                    if args.max_decisions is None
                    else min(len(reference), args.max_decisions - decisions)
                )
                obs, mask, reference = obs[:remaining], mask[:remaining], reference[:remaining]
                actions, scores, _, _ = engine.react_batch(obs, mask)
                candidate = np.asarray(actions, dtype=np.int64)
                policy = np.asarray(scores, dtype=np.float32)
                legal_scores = np.where(mask, policy, -np.inf)
                ordered = np.sort(legal_scores, axis=1)
                finite_second = np.isfinite(ordered[:, -2])
                margins.extend(
                    (ordered[finite_second, -1] - ordered[finite_second, -2]).tolist()
                )
                changed = np.flatnonzero(reference != candidate)
                mismatches += int(changed.size)
                for row in changed:
                    if len(examples) >= args.mismatch_samples:
                        break
                    examples.append(
                        {
                            "batch": item["file"],
                            "batch_position": int(row),
                            "reference_action": int(reference[row]),
                            "stable_action": int(candidate[row]),
                            "stable_margin": float(ordered[row, -1] - ordered[row, -2]),
                        }
                    )
                decisions += remaining
        finally:
            engine.close()

    rate = mismatches / decisions if decisions else None
    output = {
        "comparison_version": 1,
        "reference_contract": "legacy_amp_v1",
        "candidate_contract": "stable_advantage_v2",
        "model_sha256": imported["sha256"],
        "runtime": engine.runtime_metadata,
        "decisions": decisions,
        "action_mismatches": mismatches,
        "action_change_rate": rate,
        "threshold": args.max_action_change_rate,
        "passed": bool(decisions and rate is not None and rate <= args.max_action_change_rate),
        "stable_top2_margin": {
            "min": float(np.min(margins)) if margins else None,
            "median": float(np.median(margins)) if margins else None,
            "p01": float(np.quantile(margins, 0.01)) if margins else None,
        },
        "mismatch_samples": examples,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if output["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

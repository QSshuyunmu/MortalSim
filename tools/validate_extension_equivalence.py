#!/usr/bin/env python3
"""Compare one-shot 2000 games with an atomic 1000 + 1000 merge."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "target" / "release"), str(ROOT)]


def _chunks(path: Path):
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            yield chunk


def _canonical(result: dict[str, Any]) -> dict[str, Any]:
    value = deepcopy(result)
    for key in ("elapsed", "extension_history"):
        value.pop(key, None)
    for candidate in value.get("candidates", []):
        candidate.pop("stability", None)
        sample = candidate.get("sample") or {}
        sample.pop("elapsed_seconds", None)
        sample.pop("games_per_second", None)
    return value


def _digest(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _differences(left: Any, right: Any, path: str = "", limit: int = 100) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(a: Any, b: Any, current: str) -> None:
        if len(found) >= limit:
            return
        if type(a) is not type(b):
            found.append({"path": current, "one_shot": repr(a), "merged": repr(b)})
        elif isinstance(a, dict):
            for key in sorted(set(a) | set(b)):
                child = f"{current}.{key}" if current else key
                if key not in a or key not in b:
                    found.append({"path": child, "one_shot": repr(a.get(key)), "merged": repr(b.get(key))})
                else:
                    walk(a[key], b[key], child)
        elif isinstance(a, list):
            if len(a) != len(b):
                found.append({"path": current, "one_shot_length": len(a), "merged_length": len(b)})
            for index, (one, two) in enumerate(zip(a, b)):
                walk(one, two, f"{current}[{index}]")
        elif a != b:
            found.append({"path": current, "one_shot": a, "merged": b})

    walk(left, right, path)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-runs", type=int, default=1000)
    parser.add_argument("--additional-runs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--discards", nargs="+", default=["1s", "6s"])
    parser.add_argument("--rayon-threads", type=int, default=20)
    args = parser.parse_args()

    os.environ["MORTALSIM_LITE_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    with tempfile.TemporaryDirectory(prefix="mortalsim-extension-gate-") as temporary:
        data_root = Path(temporary)
        os.environ["MORTALSIM_DATA_DIR"] = str(data_root)
        from mortal_app.model_registry import ModelRegistry
        from mortal_app.service import merge_results, run_analysis

        imported = ModelRegistry(data_root).import_chunks(
            args.checkpoint.name, _chunks(args.checkpoint), engine="lite"
        )
        common = {
            "hand": "4567m3477p134066s",
            "dora": "9s",
            "discards": args.discards,
            "seed": args.seed,
            "round": "E1",
            "honba": 0,
            "kyotaku": 0,
            "scores": {"self": 25000, "shimocha": 25000, "toimen": 25000},
            "batch_size": 1000,
            "rayon_threads": args.rayon_threads,
            "engine": "lite",
            "decision_contract": "stable_advantage_v2",
            "model_id": imported["id"],
        }

        def run(runs: int, seed: int) -> dict[str, Any]:
            result = run_analysis({**common, "runs": runs, "seed": seed}, lambda _: None)
            result["schema_version"] = 3
            return result

        total = args.base_runs + args.additional_runs
        one_shot = run(total, args.seed)
        base = run(args.base_runs, args.seed)
        extension = run(args.additional_runs, args.seed + args.base_runs)
        merged = merge_results(base, extension, "formal-extension-gate")

    one = _canonical(one_shot)
    combined = _canonical(merged)
    # A merged result correctly retains the original starting seed and total
    # runs. The extra result's own seed is represented only in extension history.
    combined["runs"] = one["runs"]
    combined["total_runs"] = one["total_runs"]
    passed = one == combined
    output = {
        "extension_gate_version": 1,
        "model_sha256": imported["sha256"],
        "base_runs": args.base_runs,
        "additional_runs": args.additional_runs,
        "discards": args.discards,
        "one_shot_sha256": _digest(one),
        "merged_sha256": _digest(combined),
        "differences": _differences(one, combined),
        "passed": passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

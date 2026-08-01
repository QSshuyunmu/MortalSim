#!/usr/bin/env python3
"""Evaluate paired round-result drift from Legacy AMP to Formal Lite."""

from __future__ import annotations

import argparse
import gc
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "target" / "release"), str(ROOT)]


def _chunks(path: Path):
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            yield chunk


def _close_engine(engine: Any) -> None:
    close = getattr(engine, "close", None)
    if callable(close):
        close()
    del engine
    gc.collect()
    try:
        import torch

        torch.cuda.empty_cache()
    except ImportError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=50_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--discards", nargs="+", default=["1s", "6s"])
    parser.add_argument("--rayon-threads", type=int, default=20)
    parser.add_argument("--max-point-delta", type=float, default=100.0)
    parser.add_argument("--max-rate-delta", type=float, default=0.0025)
    args = parser.parse_args()

    os.environ["MORTALSIM_LITE_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    os.environ["MORTAL_TRACE"] = "1"
    with tempfile.TemporaryDirectory(prefix="mortalsim-migration-gate-") as temporary:
        data_root = Path(temporary)
        os.environ["MORTALSIM_DATA_DIR"] = str(data_root)
        from mortal_app.model_registry import ModelRegistry
        from mortal_app.service import OUTCOMES, _load_engine, _mean, _parse_inputs, _summarize
        import libriichi

        imported = ModelRegistry(data_root).import_chunks(
            args.checkpoint.name, _chunks(args.checkpoint), engine="lite"
        )
        model_id = str(imported["id"])
        request = {
            "hand": "4567m3477p134066s",
            "dora": "9s",
            "discards": args.discards,
            "runs": args.runs,
            "seed": args.seed,
            "round": "E1",
            "honba": 0,
            "kyotaku": 0,
            "scores": {"self": 25000, "shimocha": 25000, "toimen": 25000},
            "batch_size": 1000,
            "rayon_threads": args.rayon_threads,
            "model_id": model_id,
        }
        hand, first_tsumo, dora, discards, runs, seed, context, _, _ = _parse_inputs(request)
        runner = libriichi.arena.CustomKyokuRunner()

        def run_contract(contract: str, engine_name: str) -> tuple[dict[str, Any], dict[str, Any]]:
            engine, _, _ = _load_engine(model_id, engine_name, contract)
            summaries: dict[str, Any] = {}
            runtime = dict(getattr(engine, "runtime_metadata", {}))
            try:
                for action in discards:
                    started = time.perf_counter()
                    rows: list[dict[str, Any]] = []
                    for offset in range(0, runs, 1000):
                        rows.extend(
                            runner.run_many(
                                engine=engine,
                                kyoku=context["kyoku"],
                                honba=context["honba"],
                                kyotaku=context["kyotaku"],
                                bakaze=context["bakaze"],
                                oya=context["oya"],
                                scores=context["scores"],
                                dora_marker=dora,
                                main_haipai=hand,
                                first_discard=action["engine_tile"],
                                first_tsumo=first_tsumo,
                                first_riichi=action["riichi"],
                                seed_start=(seed + offset, 0xDEAD),
                                count=min(1000, runs - offset),
                            )
                        )
                    summary = _summarize(
                        rows,
                        int(context["oya"]),
                        action["tile"],
                        time.perf_counter() - started,
                        first_riichi=action["riichi"],
                    )
                    summary["_trace_hashes"] = [row.get("trace_hash") for row in rows]
                    summaries[action["candidate"]] = summary
            finally:
                _close_engine(engine)
            return summaries, runtime

        legacy, legacy_runtime = run_contract("legacy_amp_v1", "python")
        stable, stable_runtime = run_contract("stable_advantage_v2", "lite")

    candidates = []
    passed = True
    for candidate in legacy:
        left, right = legacy[candidate], stable[candidate]
        point_delta = _mean(
            b - a
            for a, b in zip(left["_points"], right["_points"])
            if a is not None and b is not None
        )
        outcome_deltas = {
            outcome: _mean(
                b - a
                for a, b in zip(
                    left["_indicators"][outcome], right["_indicators"][outcome]
                )
                if a is not None and b is not None
            )
            for outcome in OUTCOMES
        }
        trace_changes = sum(
            a != b for a, b in zip(left["_trace_hashes"], right["_trace_hashes"])
        )
        point_ok = bool(
            point_delta.get("ci95")
            and point_delta["ci95"][0] >= -args.max_point_delta
            and point_delta["ci95"][1] <= args.max_point_delta
        )
        rates_ok = all(
            abs(float(item.get("value") or 0.0)) <= args.max_rate_delta
            for item in outcome_deltas.values()
        )
        passed = passed and point_ok and rates_ok
        candidates.append(
            {
                "candidate": candidate,
                "paired_point_delta": point_delta,
                "outcome_rate_deltas": outcome_deltas,
                "trace_changes": trace_changes,
                "trace_change_rate": trace_changes / args.runs,
                "legacy_average_point": left["avg_point"],
                "stable_average_point": right["avg_point"],
                "point_gate_passed": point_ok,
                "rate_gate_passed": rates_ok,
            }
        )
    output = {
        "migration_gate_version": 1,
        "model_sha256": imported["sha256"],
        "runs_per_candidate": args.runs,
        "seed": args.seed,
        "legacy_runtime": legacy_runtime,
        "stable_runtime": stable_runtime,
        "thresholds": {
            "paired_point_ci": [-args.max_point_delta, args.max_point_delta],
            "outcome_rate_delta": args.max_rate_delta,
        },
        "candidates": candidates,
        "passed": passed,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

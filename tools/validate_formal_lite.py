#!/usr/bin/env python3
"""Produce a deterministic per-round signature for the Formal Lite GPU gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "target" / "release"), str(ROOT)]


def checkpoint_chunks(path: Path):
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            yield chunk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runs", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--discards", nargs="+", default=["1s", "6s"])
    parser.add_argument("--hand", default="4567m3477p134066s")
    parser.add_argument("--dora", default="9s")
    parser.add_argument("--round", default="E1")
    parser.add_argument("--rayon-threads", type=int, default=20)
    args = parser.parse_args()

    os.environ["MORTALSIM_LITE_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    os.environ["MORTAL_TRACE"] = "1"
    with tempfile.TemporaryDirectory(prefix="mortalsim-formal-gate-") as temporary:
        data_root = Path(temporary)
        os.environ["MORTALSIM_DATA_DIR"] = str(data_root)
        from mortal_app.model_registry import ModelRegistry
        from mortal_app.service import _load_engine, _parse_inputs, _summarize

        registry = ModelRegistry(data_root)
        imported = registry.import_chunks(
            args.checkpoint.name,
            checkpoint_chunks(args.checkpoint),
            engine="lite",
        )
        model_id = str(imported["id"])
        import libriichi

        runner = libriichi.arena.CustomKyokuRunner()
        output: dict[str, object] = {
            "validation_version": 1,
            "decision_contract": "stable_advantage_v2",
            "model_sha256": imported["sha256"],
            "runs": args.runs,
            "seed": args.seed,
            "candidates": [],
        }
        for discard in args.discards:
            request = {
                "hand": args.hand,
                "dora": args.dora,
                "discards": [discard],
                "runs": args.runs,
                "seed": args.seed,
                "round": args.round,
                "honba": 0,
                "kyotaku": 0,
                "scores": {"self": 25000, "shimocha": 25000, "toimen": 25000},
                "batch_size": 1000,
                "rayon_threads": args.rayon_threads,
                "engine": "lite",
                "decision_contract": "stable_advantage_v2",
                "model_id": model_id,
            }
            hand, first_tsumo, dora, discards, runs, seed, context, _, _ = _parse_inputs(request)
            engine, _, _ = _load_engine(model_id, "lite", "stable_advantage_v2")
            started = time.perf_counter()
            rows = []
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
                        first_discard=discards[0]["engine_tile"],
                        first_tsumo=first_tsumo,
                        first_riichi=discards[0]["riichi"],
                        seed_start=(seed + offset, 0xDEAD),
                        count=min(1000, runs - offset),
                    )
                )
            elapsed = time.perf_counter() - started
            signatures = []
            errors = 0
            for row in sorted(rows, key=lambda item: tuple(item["seed"])):
                result = row.get("result") or {}
                errors += int(bool(result.get("error")))
                signatures.append(
                    {
                        "seed": row.get("seed"),
                        "trace_hash": row.get("trace_hash"),
                        "outcome": result.get("outcome"),
                        "final_scores": result.get("final_scores"),
                        "score_deltas": result.get("score_deltas"),
                        "error": result.get("error"),
                    }
                )
            digest = hashlib.sha256(
                json.dumps(signatures, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            summary = _summarize(rows, int(context["oya"]), discard, elapsed)
            output["runtime"] = engine.runtime_metadata
            output["candidates"].append(
                {
                    "discard": discard,
                    "games": len(rows),
                    "errors": errors,
                    "trace_result_sha256": digest,
                    "elapsed_seconds": elapsed,
                    "games_per_second": len(rows) / elapsed,
                    "average_point": summary["avg_point"],
                    "win_rate": summary["agari_rate"],
                    "deal_in_rate": summary["houjuu_rate"],
                }
            )
            engine.close()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
        print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

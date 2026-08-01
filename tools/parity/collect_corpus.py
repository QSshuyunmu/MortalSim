#!/usr/bin/env python3
"""Collect immutable Legacy AMP decision batches and round trace identities."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "target" / "release"), str(ROOT)]

from mortal_app.model_registry import DEFAULT_MODEL_ID  # noqa: E402
from mortal_app.service import _load_engine, _parse_inputs  # noqa: E402


class RecordingEngine:
    def __init__(self, delegate: Any, output_dir: Path) -> None:
        self.delegate = delegate
        self.output_dir = output_dir
        self.call_index = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self.delegate, name)

    def react_batch(self, obs: Any, masks: Any, invisible_obs: Any = None):
        obs_array = np.ascontiguousarray(obs, dtype=np.float32)
        mask_array = np.ascontiguousarray(masks, dtype=np.bool_)
        actions, q_values, returned_masks, greedy = self.delegate.react_batch(
            obs_array, mask_array, invisible_obs
        )
        path = self.output_dir / f"batch-{self.call_index:06d}.npz"
        np.savez_compressed(
            path,
            obs=obs_array,
            mask=mask_array,
            reference_action=np.asarray(actions, dtype=np.int16),
            reference_q=np.asarray(q_values, dtype=np.float32),
            batch_position=np.arange(obs_array.shape[0], dtype=np.int32),
        )
        self.call_index += 1
        return actions, q_values, returned_masks, greedy


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--hand", default="4567m3477p134066s")
    parser.add_argument("--dora", default="9s")
    parser.add_argument("--discard", default="1s")
    parser.add_argument("--runs", type=int, default=300)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-size", type=int, default=300)
    parser.add_argument("--rayon-threads", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    if args.output.exists() and any(args.output.iterdir()) and not args.overwrite:
        raise RuntimeError("output directory is not empty; pass --overwrite explicitly")
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ["MORTAL_TRACE"] = "1"
    request = {
        "hand": args.hand,
        "dora": args.dora,
        "discards": [args.discard],
        "runs": args.runs,
        "seed": args.seed,
        "round": "E1",
        "honba": 0,
        "kyotaku": 0,
        "scores": {"self": 25000, "shimocha": 25000, "toimen": 25000},
        "batch_size": args.batch_size,
        "rayon_threads": args.rayon_threads,
        "engine": "python",
        "decision_contract": "legacy_amp_v1",
        "model_id": args.model_id,
    }
    hand, first_tsumo, dora, discards, runs, seed, context, _, _ = _parse_inputs(request)
    engine, _, model = _load_engine(args.model_id, "python", "legacy_amp_v1")
    recorder = RecordingEngine(engine, args.output)

    import libriichi

    rows = libriichi.arena.CustomKyokuRunner().run_many(
        engine=recorder,
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
        seed_start=(seed, 0xDEAD),
        count=runs,
    )
    batches = sorted(args.output.glob("batch-*.npz"))
    manifest = {
        "corpus_version": 1,
        "decision_contract": "legacy_amp_v1",
        "request": request,
        "model": {key: model.get(key) for key in ("id", "sha256", "version", "conv_channels", "num_blocks")},
        "batch_files": [
            {"file": path.name, "sha256": file_sha256(path)} for path in batches
        ],
        "rounds": [
            {
                "seed": row.get("seed"),
                "trace_hash": row.get("trace_hash"),
                "outcome": (row.get("result") or {}).get("outcome"),
                "final_scores": (row.get("result") or {}).get("final_scores"),
                "error": (row.get("result") or {}).get("error"),
            }
            for row in rows
        ],
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {manifest_path}: {len(rows)} rounds, {len(batches)} decision batches")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

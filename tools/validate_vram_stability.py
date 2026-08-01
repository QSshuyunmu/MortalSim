#!/usr/bin/env python3
"""Run Formal Lite continuously and detect sustained VRAM growth."""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "target" / "release"), str(ROOT)]


def _chunks(path: Path):
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            yield chunk


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--duration-seconds", type=int, default=1800)
    parser.add_argument("--rayon-threads", type=int, default=20)
    parser.add_argument("--max-growth-mib", type=float, default=128.0)
    parser.add_argument("--overhead-pairs", type=int, default=3)
    parser.add_argument("--max-monitor-overhead-percent", type=float, default=1.0)
    args = parser.parse_args()
    if args.overhead_pairs < 1:
        parser.error("--overhead-pairs must be at least 1")
    if args.max_monitor_overhead_percent < 0:
        parser.error("--max-monitor-overhead-percent cannot be negative")

    os.environ["MORTALSIM_LITE_RUNTIME_DIR"] = str(args.runtime_dir.resolve())
    with tempfile.TemporaryDirectory(prefix="mortalsim-vram-gate-") as temporary:
        data_root = Path(temporary)
        os.environ["MORTALSIM_DATA_DIR"] = str(data_root)
        from mortal_app.gpu_monitor import GpuMonitor
        from mortal_app.model_registry import ModelRegistry
        from mortal_app.service import _load_engine, _parse_inputs
        import libriichi

        imported = ModelRegistry(data_root).import_chunks(
            args.checkpoint.name, _chunks(args.checkpoint), engine="lite"
        )
        engine, _, _ = _load_engine(
            str(imported["id"]), "lite", "stable_advantage_v2"
        )
        request = {
            "hand": "4567m3477p134066s",
            "dora": "9s",
            "discards": ["1s"],
            "runs": 1000,
            "seed": 42,
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
        hand, first_tsumo, dora, discards, _, seed, context, _, _ = _parse_inputs(request)
        runner = libriichi.arena.CustomKyokuRunner()

        def run_batch(seed_offset: int):
            return runner.run_many(
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
                seed_start=(seed + seed_offset, 0xDEAD),
                count=1000,
            )

        run_batch(0)  # Warm allocations before measuring growth.

        unmonitored_durations: list[float] = []
        monitored_durations: list[float] = []
        overhead_errors = 0
        next_seed_batch = 1
        for pair in range(args.overhead_pairs):
            before = time.perf_counter()
            rows = run_batch(next_seed_batch * 1000)
            unmonitored_durations.append(time.perf_counter() - before)
            overhead_errors += sum(bool((row.get("result") or {}).get("error")) for row in rows)
            next_seed_batch += 1

            pair_monitor = GpuMonitor(
                lambda _: None,
                data_root / f"telemetry-overhead-{pair}.csv",
                interval=2.0,
            )
            pair_monitor.start()
            try:
                before = time.perf_counter()
                rows = run_batch(next_seed_batch * 1000)
                monitored_durations.append(time.perf_counter() - before)
                overhead_errors += sum(bool((row.get("result") or {}).get("error")) for row in rows)
            finally:
                pair_monitor.stop()
            next_seed_batch += 1

        unmonitored_median = statistics.median(unmonitored_durations)
        monitored_median = statistics.median(monitored_durations)
        monitor_overhead_percent = (
            (monitored_median / unmonitored_median - 1.0) * 100.0
            if unmonitored_median > 0
            else None
        )
        events: list[dict[str, object]] = []
        monitor = GpuMonitor(events.append, data_root / "telemetry.csv", interval=2.0)
        started = time.perf_counter()
        games = errors = batches = 0
        monitor.start()
        try:
            while time.perf_counter() - started < args.duration_seconds:
                rows = run_batch((next_seed_batch + batches) * 1000)
                games += len(rows)
                errors += sum(bool((row.get("result") or {}).get("error")) for row in rows)
                batches += 1
        finally:
            monitor.stop()
            engine.close()
        elapsed = time.perf_counter() - started

        memory = [
            float(sample["memory.used"])
            for sample in monitor.samples
            if sample.get("memory.used") is not None
        ]
        quartile = max(1, len(memory) // 4)
        first = statistics.median(memory[:quartile]) if memory else None
        last = statistics.median(memory[-quartile:]) if memory else None
        growth = last - first if first is not None and last is not None else None
        passed = bool(
            len(memory) >= 10
            and growth is not None
            and growth <= args.max_growth_mib
            and errors == 0
            and overhead_errors == 0
            and monitor.summary()["critical_samples"] == 0
            and monitor_overhead_percent is not None
            and monitor_overhead_percent <= args.max_monitor_overhead_percent
        )
        output = {
            "stability_version": 1,
            "model_sha256": imported["sha256"],
            "runtime": engine.runtime_metadata,
            "duration_seconds": elapsed,
            "games": games,
            "batches": batches,
            "errors": errors,
            "games_per_second": games / elapsed,
            "monitor_overhead": {
                "pairs": args.overhead_pairs,
                "games": args.overhead_pairs * 2000,
                "errors": overhead_errors,
                "unmonitored_median_seconds_per_1000": unmonitored_median,
                "monitored_median_seconds_per_1000": monitored_median,
                "overhead_percent": monitor_overhead_percent,
                "max_overhead_percent": args.max_monitor_overhead_percent,
                "passed": bool(
                    overhead_errors == 0
                    and monitor_overhead_percent is not None
                    and monitor_overhead_percent <= args.max_monitor_overhead_percent
                ),
            },
            "gpu": monitor.summary(),
            "memory_first_quartile_median_mib": first,
            "memory_last_quartile_median_mib": last,
            "memory_growth_mib": growth,
            "max_growth_mib": args.max_growth_mib,
            "passed": passed,
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())

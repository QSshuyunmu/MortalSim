# -*- coding: utf-8 -*-
"""天梯吞吐微基准 —— 变量隔离的快速实验台（跑在 Atozuke 上）。

目的：用 1-seed 小桌把「一次实验一小时」缩短到「整个矩阵 10~15 分钟」，
只用于调参决策；生产环境仍跑完整的 64 半庄桌。

测量项：
  A. 单会话推理延迟：batch 1/4/16 各 10 次（理论下限）
  B. 桌级并发吞吐：N 桌 × 1 seed（4 半庄/桌），测 半庄/秒 与加速比
     变量：会话独占 vs 共享 × intra 1/2 × 桌数 2/6/10
  C. 确定性校验：各变体同种子结果必须一致（哈希对比）

用法：
  python bench_ladder.py --models-dir C:/arena/models/tsypx --onnx-dir C:/arena/models/onnx
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path("C:/arena")
if "ORT_DYLIB_PATH" not in os.environ and (ROOT / "onnxruntime.dll").is_file():
    os.environ["ORT_DYLIB_PATH"] = str(ROOT / "onnxruntime.dll")
for p in (str(ROOT), str(ROOT / "mortal"), str(ROOT / "pyd_native")):
    if Path(p).is_dir() and p not in sys.path:
        sys.path.insert(0, p)

import libriichi  # noqa: E402

HAS_ONNX_ENGINE = hasattr(libriichi.arena, "MortalOnnxEngine")
SEED_BASE = 900000          # 基准专用 seed 段，不与生产混淆
BENCH_TABLES_MODELS = ["luckyj_clone_v1", "distill_nova_v2", "Bin_0910",
                       "distill_consensus_v3", "zensoku", "distill_nova"]


def build_engine(onnx_dir: Path, mid: str, intra: int):
    return libriichi.arena.MortalOnnxEngine(str(onnx_dir / f"{mid}.onnx"), 0, False,
                                            intra, name=mid)


def bench_inference_latency(onnx_dir: Path, intra: int) -> dict:
    """单会话 batch 延迟：每 batch 规模 10 次取中位。"""
    eng = build_engine(onnx_dir, "luckyj_clone_v1", intra)
    shape = libriichi.consts.obs_shape(4)
    out = {}
    for batch in (1, 4, 16):
        obs = [0.0] * (batch * shape[0] * shape[1])
        masks = [[True] * libriichi.consts.ACTION_SPACE for _ in range(batch)]
        lat = []
        for _ in range(10):
            t0 = time.perf_counter()
            eng.infer_direct(obs, masks, shape[0], shape[1])
            lat.append(time.perf_counter() - t0)
        lat.sort()
        out[f"batch{batch}"] = round(lat[len(lat) // 2] * 1000, 1)  # ms
    return out


def run_tables(arena, engines_by_table, seed_base, batch_seeds):
    """并发跑 N 桌，返回 (hanchans, 秒, 结果哈希)。"""
    t0 = time.perf_counter()
    results = {}

    def one(table_id, engines):
        rows = arena.py_vs_py_detailed(*engines, (seed_base + table_id, 0), batch_seeds)
        h = hashlib.md5()
        n = 0
        for _seed, _k, _split, ranks, scores in rows:
            n += 1
            h.update(f"{list(ranks)}{list(scores)}".encode())
        return n, h.hexdigest()[:12], list(rows[0][3]) if rows else None

    with ThreadPoolExecutor(max_workers=len(engines_by_table)) as ex:
        futs = [(tid, ex.submit(one, tid, es)) for tid, es in enumerate(engines_by_table)]
        total_h = 0
        for _tid, fut in futs:
            n, digest, first_ranks = fut.result()
            total_h += n
            results[_tid] = {"hanchans": n, "hash": digest, "first_ranks": first_ranks}
    elapsed = time.perf_counter() - t0
    return total_h, elapsed, results


def bench_tables(models: list[str], onnx_dir: Path, n_tables: int, intra: int,
                 exclusive: bool, batch_seeds: int) -> dict:
    arena = libriichi.arena.FourPlayer(disable_progress_bar=True)
    engines_by_table = []
    if exclusive:
        # 每桌独占一套会话
        for _t in range(n_tables):
            engines_by_table.append([build_engine(onnx_dir, m, intra)
                                     for m in models[:4]])
    else:
        # 同模型共享单会话（模拟旧 runner 的共享缓存）
        shared = {m: build_engine(onnx_dir, m, intra) for m in models}
        for t in range(n_tables):
            engines_by_table.append([shared[models[(t + s) % len(models)]]
                                     for s in range(4)])

    h, sec, results = run_tables(arena, engines_by_table, SEED_BASE, batch_seeds)
    rate = h / sec if sec > 0 else 0
    # 确定性哈希：所有变体同种子必须一致
    combo = json.dumps(results, sort_keys=True)
    determinism = hashlib.md5(combo.encode()).hexdigest()[:12]
    return {"hanchans": h, "seconds": round(sec, 1),
            "hanchan_per_min": round(rate * 60, 2), "determinism": determinism}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models-dir", default="C:/arena/models/tsypx")
    ap.add_argument("--onnx-dir", default="C:/arena/models/onnx")
    ap.add_argument("--seats", type=int, default=4, help="每桌模型数")
    a = ap.parse_args()
    onnx_dir = Path(a.onnx_dir)
    models = BENCH_TABLES_MODELS[: a.seats]
    results = {}

    print("=== A. 单会话推理延迟 (ms, 中位/10次) ===")
    for intra in (1, 2):
        results[f"intra{intra}_latency"] = bench_inference_latency(onnx_dir, intra)
        print(f"  intra={intra}: {results[f'intra{intra}_latency']}")

    print()
    print("=== B. 桌级并发吞吐 (每桌 1 seed = 4 半庄) ===")
    variants = [
        ("exclusive_intra1_t2", dict(n_tables=2, intra=1, exclusive=True)),
        ("exclusive_intra2_t2", dict(n_tables=2, intra=2, exclusive=True)),
        ("exclusive_intra2_t6", dict(n_tables=6, intra=2, exclusive=True)),
        ("shared_intra2_t6", dict(n_tables=6, intra=2, exclusive=False)),
        ("exclusive_intra1_t6", dict(n_tables=6, intra=1, exclusive=True)),
        ("exclusive_intra2_t10", dict(n_tables=10, intra=2, exclusive=True)),
    ]
    det_hashes = {}
    for name, kw in variants:
        try:
            r = bench_tables(models, onnx_dir, batch_seeds=1, **kw)
            results[name] = r
            det_hashes[name] = r["determinism"]
            print(f"  {name:<22} {r['hanchans']:>3} 半庄 {r['seconds']:>6.1f}s  "
                  f"= {r['hanchan_per_min']:>6.2f} 半庄/分  确定性 {r['determinism']}")
        except Exception as e:
            print(f"  {name:<22} FAIL {type(e).__name__}: {str(e)[:100]}")

    print()
    print("=== C. 确定性一致性（同种子跨变体）===")
    uniq = set(det_hashes.values())
    print(f"  唯一哈希数: {len(uniq)} {'-> 全部一致 ✅' if len(uniq) == 1 else '-> 存在差异 ❌'} {det_hashes}")

    out = Path("C:/arena/ladder/bench_result.json")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果已写 {out}")


if __name__ == "__main__":
    main()

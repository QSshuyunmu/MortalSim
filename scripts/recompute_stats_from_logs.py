#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从已落盘的 mjai 牌谱语料统一重算天梯统计（权威口径）。

设计取舍
--------
runner 侧有一个「增量累加器」（每局结算时把 Stat 计数加进 player_stats 表），
优点是零额外 I/O；缺点是口径一旦要改就得从头再来、且中途失败会漏计。

本脚本走另一条路——**从原始牌谱全量重算**：
  * 数据源：<log_dir>/YYYYMMDD/*.json.gz（runner 每局落盘，start_game.names
    已改写为 avatar_id，因此可按账号精确统计）
  * 计算：libriichi.stat.Stat.from_dir(dir, avatar_id) —— 与 keqing1-workbench
    的 build_platform_account_report.py 完全同源的口径
  * 产出：player_stats 表（与增量累加器同一张表，可互相校验/覆盖）

用法：
  python recompute_stats_from_logs.py                       # 全量重算并写回 DB
  python recompute_stats_from_logs.py --dry-run             # 只打印，不写库
  python recompute_stats_from_logs.py --from 20260928       # 只算指定日期起
  python recompute_stats_from_logs.py --verify              # 与现有表逐字段对比
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path("C:/arena")
if "ORT_DYLIB_PATH" not in os.environ and (ROOT / "onnxruntime.dll").is_file():
    os.environ["ORT_DYLIB_PATH"] = str(ROOT / "onnxruntime.dll")
for p in (str(ROOT), str(ROOT / "mortal"), str(ROOT / "pyd_native"),
          str(ROOT / "ladder"), str(ROOT / "ladder_tmp")):
    if Path(p).is_dir() and p not in sys.path:
        sys.path.insert(0, p)

import libriichi  # noqa: E402

FIELDS = ("games", "rounds", "agari", "houjuu", "fuuro", "fuuro_num", "riichi")
RATES = ("agari_rate", "houjuu_rate", "fuuro_rate", "riichi_rate")


def scan_corpus(log_dir: Path, since: str | None) -> tuple[list[Path], dict]:
    """扫描语料，返回 (文件列表, 每个 avatar 的文件数)。"""
    files: list[Path] = []
    per_avatar: dict[str, int] = {}
    days = sorted(p for p in log_dir.iterdir() if p.is_dir()) if log_dir.is_dir() else []
    for day in days:
        if since and day.name < since:
            continue
        files.extend(sorted(day.glob("*.json.gz")))
    if not files:
        return [], {}
    # 用 start_game.names 建索引（避免 from_dir 反复扫全目录）
    import gzip
    for f in files:
        try:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                head = json.loads(fh.readline())
            for nm in head.get("names", []):
                per_avatar[nm] = per_avatar.get(nm, 0) + 1
        except Exception:
            continue
    return files, per_avatar


def recompute(log_dir: Path, since: str | None) -> dict:
    """对每个 avatar 用 Stat.from_dir 在全量语料上统计。"""
    files, per_avatar = scan_corpus(log_dir, since)
    if not files:
        return {}
    print(f"[scan] 语料 {len(files)} 局，覆盖 {len(per_avatar)} 个账号 "
          f"（目录 {log_dir}）")
    out = {}
    t0 = time.time()
    for i, aid in enumerate(sorted(per_avatar), 1):
        try:
            st = libriichi.stat.Stat.from_dir(str(log_dir), aid, True)
        except Exception as e:
            print(f"  [warn] {aid} 统计失败: {type(e).__name__}: {str(e)[:80]}")
            continue
        row = {"games": int(st.game)}
        for f in ("round", "agari", "houjuu", "fuuro", "fuuro_num", "riichi"):
            row["rounds" if f == "round" else f] = int(getattr(st, f))
        row["rates"] = {r: round(float(getattr(st, r)), 6) for r in RATES}
        out[aid] = row
        if i % 5 == 0 or i == len(per_avatar):
            print(f"  ... {i}/{len(per_avatar)} 席 ({time.time()-t0:.1f}s)", flush=True)
    return out


def write_db(db_path: Path, stats: dict) -> int:
    con = sqlite3.connect(str(db_path), timeout=60)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS player_stats ("
                    "avatar_id TEXT PRIMARY KEY, games INT, rounds INT, agari INT, "
                    "houjuu INT, fuuro INT, fuuro_num INT, riichi INT)")
        con.executemany(
            "INSERT OR REPLACE INTO player_stats VALUES (?,?,?,?,?,?,?,?)",
            [(aid, v["games"], v["rounds"], v["agari"], v["houjuu"],
              v["fuuro"], v["fuuro_num"], v["riichi"]) for aid, v in stats.items()])
        con.commit()
        return len(stats)
    finally:
        con.close()


def verify(db_path: Path, stats: dict) -> None:
    """与库内现有值对比（判断增量累加器是否漏计）。"""
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        cur = {r[0]: r[1:] for r in con.execute(
            "SELECT avatar_id, games, rounds, agari, houjuu, fuuro, fuuro_num, "
            "riichi FROM player_stats")}
    finally:
        con.close()
    print(f"{'账号':<14}{'轮次(重算/库内)':>20}{'和(重/库)':>16}{'铳(重/库)':>14}")
    print("-" * 70)
    for aid in sorted(stats):
        v = stats[aid]
        d = cur.get(aid)
        if d is None:
            print(f"{aid:<14}{v['rounds']:>10}{'/  —':>10}{v['agari']:>8}{'/  —':>8}{v['houjuu']:>7}{'/  —':>7}")
        else:
            flag = "" if (v["rounds"] == d[1] and v["agari"] == d[2]) else "  <== 差异"
            print(f"{aid:<14}{v['rounds']:>10}{'/' + str(d[1]):>10}"
                  f"{v['agari']:>8}{'/' + str(d[2]):>8}{v['houjuu']:>7}{'/' + str(d[3]):>7}{flag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-dir", default=str(ROOT / "ladder_logs"))
    ap.add_argument("--db", default=str(ROOT / "ladder_results.db"))
    ap.add_argument("--since", default=None, help="只统计该日期（YYYYMMDD）起的语料")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写库")
    ap.add_argument("--verify", action="store_true", help="与库内现有值对比")
    a = ap.parse_args()

    log_dir = Path(a.log_dir)
    if not log_dir.is_dir():
        print(f"语料目录不存在: {log_dir}（runner 尚未落盘任何牌谱）")
        return 1

    stats = recompute(log_dir, a.since)
    if not stats:
        print("未统计到任何账号")
        return 1

    print()
    if a.verify:
        verify(Path(a.db), stats)
    if not a.dry_run:
        n = write_db(Path(a.db), stats)
        print(f"\n[ok] player_stats 已重写 {n} 席（来源：{log_dir} 全量牌谱语料）")
    else:
        print("[dry-run] 未写库。汇总：")
        for aid in sorted(stats)[:8]:
            v = stats[aid]
            print(f"  {aid:<14} {v['games']:>5} 局 {v['rounds']:>6} 轮  "
                  f"和{v['rates']['agari_rate']:.3f} 铳{v['rates']['houjuu_rate']:.3f} "
                  f"副露{v['rates']['fuuro_rate']:.3f} 立直{v['rates']['riichi_rate']:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

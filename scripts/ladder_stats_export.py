# -*- coding: utf-8 -*-
"""天梯全量榜单导出：按【物理模型】聚合，输出 TSV 供本机 QQ 推送器格式化。

为什么按模型聚合：一座天梯上有 30 个席位，但只有 11 套权重。分身之间是同权重、
互为重复样本，合并后才是这个模型的真实水平；也让各模型间的样本量可比。

数据源（都是事实源，不做任何推算）：
  ladder_games  -> 半庄数 / 顺位分布 / 房间分布（逐半庄簿记）
  player_stats  -> 和牌 / 放铳 / 立直 / 副露（逐局累计，与 libriichi Stat 同口径）
  ladder_state  -> 各席位当前段位与 R（荣誉：已回收席位也计入，它的对局是真实打出来的）

用法（在 Atozuke 上）：
  python -X utf8 ladder_stats_export.py [--db C:/arena/ladder_results.db]
                                       [--state C:/arena/ladder_state.json]
                                       [--out C:/arena/_ladder_stats.tsv]
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

COLS = ["model", "seats", "games", "games_houou", "games_tokujou",
        "r1", "r2", "r3", "r4", "rounds", "agari", "houjuu", "riichi", "fuuro",
        "dan_max", "dan_min", "r_avg", "r_best", "recycled"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="C:/arena/ladder_results.db")
    ap.add_argument("--state", default="C:/arena/ladder_state.json")
    ap.add_argument("--out", default="C:/arena/_ladder_stats.tsv")
    a = ap.parse_args()

    con = sqlite3.connect(str(a.db), timeout=30)
    con.row_factory = sqlite3.Row

    # 逐半庄：半庄数 / 顺位 / 房间
    agg = {}
    for r in con.execute(
            "SELECT model_id, avatar_id, rank, room FROM ladder_games"):
        m = agg.setdefault(r["model_id"], {
            "model": r["model_id"], "seats": set(), "games": 0,
            "games_houou": 0, "games_tokujou": 0,
            "r1": 0, "r2": 0, "r3": 0, "r4": 0})
        m["seats"].add(r["avatar_id"])
        m["games"] += 1
        if r["room"] == "houou":
            m["games_houou"] += 1
        elif r["room"] == "tokujou":
            m["games_tokujou"] += 1
        k = "r%d" % int(r["rank"])
        if k in m:
            m[k] += 1

    # 逐局：和 / 铳 / 立直 / 副露（player_stats 已按 avatar 累计）
    seat_model = {}
    for r in con.execute("SELECT DISTINCT avatar_id, model_id FROM ladder_games"):
        seat_model[r["avatar_id"]] = r["model_id"]
    stats = {}
    try:
        for r in con.execute("SELECT avatar_id, rounds, agari, houjuu, riichi, fuuro "
                             "FROM player_stats"):
            mid = seat_model.get(r["avatar_id"])
            if mid is None:
                continue
            s = stats.setdefault(mid, {"rounds": 0, "agari": 0, "houjuu": 0,
                                       "riichi": 0, "fuuro": 0})
            for k in ("rounds", "agari", "houjuu", "riichi", "fuuro"):
                s[k] += int(r[k] or 0)
    except sqlite3.OperationalError:
        pass

    # 当前段位/R（含已回收席位；它的对局已计入上面，这里只取终态做展示）
    state = {}
    sp = Path(a.state)
    if sp.is_file():
        try:
            state = json.loads(sp.read_text(encoding="utf-8")).get("players", {})
        except Exception:
            state = {}

    rr = {}
    for aid, v in state.items():
        mid = seat_model.get(aid)
        if mid is None:
            continue
        d = rr.setdefault(mid, {"dans": [], "rs": [], "retired": 0})
        d["dans"].append(int(v.get("dan") or 0))
        d["rs"].append(float(v.get("rating") or 0.0))
        if v.get("retired"):
            d["retired"] += 1

    rows = []
    for mid, m in agg.items():
        s = stats.get(mid, {})
        d = rr.get(mid, {})
        dans = [x for x in d.get("dans", []) if x]
        rs = d.get("rs", [])
        rows.append({
            "model": mid, "seats": len(m["seats"]), "games": m["games"],
            "games_houou": m["games_houou"], "games_tokujou": m["games_tokujou"],
            "r1": m["r1"], "r2": m["r2"], "r3": m["r3"], "r4": m["r4"],
            "rounds": s.get("rounds", 0), "agari": s.get("agari", 0),
            "houjuu": s.get("houjuu", 0), "riichi": s.get("riichi", 0),
            "fuuro": s.get("fuuro", 0),
            "dan_max": max(dans) if dans else 0,
            "dan_min": min(dans) if dans else 0,
            "r_avg": (sum(rs) / len(rs)) if rs else 0.0,
            "r_best": max(rs) if rs else 0.0,
            "recycled": d.get("retired", 0),
        })

    # 排序：段位上限 -> 平均 R -> 半庄数（与天梯自身的强弱口径一致）
    rows.sort(key=lambda x: (-x["dan_max"], -x["r_avg"], -x["games"]))
    out = Path(a.out)
    with out.open("w", encoding="utf-8", newline="") as f:
        f.write("\t".join(COLS) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) for c in COLS) + "\n")
    print("[ladder-stats] %d 款模型 / %d 半庄 -> %s"
          % (len(rows), sum(x["games"] for x in rows), out))


if __name__ == "__main__":
    main()

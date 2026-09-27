# -*- coding: utf-8 -*-
"""状态链不变量检验：同一账号本行的 before 态必须严格等于上一行的 after 态。

链一旦断裂 => 进程重启时内存态被回滚（快照陈旧），已入账的段位/PT/R 被抹掉。
"""
import sqlite3, sys
from collections import defaultdict
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DAN_CN = {1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段", 6: "六段",
          7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"}

con = sqlite3.connect("D:/tenhoulib/.diag/db_audit.db")
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT match_id, seed_idx, split, avatar_id, pt_before, pt_after, dan_before, dan_after, "
    "rating_before, rating_after FROM ladder_games ORDER BY match_id ASC").fetchall()

prev = {}
breaks = []
for r in rows:
    aid = r["avatar_id"]
    if aid in prev:
        p = prev[aid]
        if (p["pt_after"], p["dan_after"], p["rating_after"]) != \
           (r["pt_before"], r["dan_before"], r["rating_before"]):
            breaks.append({
                "aid": aid, "prev_match": p["match_id"], "prev_seed": p["seed_idx"],
                "match": r["match_id"], "seed": r["seed_idx"],
                "prev": (p["dan_after"], p["pt_after"], round(p["rating_after"], 2)),
                "now": (r["dan_before"], r["pt_before"], round(r["rating_before"], 2)),
            })
    prev[aid] = r

print("=" * 100)
print("状态链不变量：本行 before 态 == 上一行 after 态")
print("=" * 100)
if not breaks:
    print("  状态链完整：没有任何账号的状态被回滚 ✓")
else:
    print(f"  ✗ 断裂 {len(breaks)} 处，涉及 {len({b['aid'] for b in breaks})} 个账号")
    print()
    print(f"  {'账号':<14}{'断裂处seed':>12}{'前态(段/pt/R)':>26}{'现态(段/pt/R)':>26}    判定")
    print("  " + "-" * 96)
    for b in breaks[:30]:
        pd, pp, pr = b["prev"]
        nd, np_, nr = b["now"]
        # 判定：回滚（现态落后）/ 跳变（现态超前）
        kind = "回滚" if (nd, np_) < (nd, np_) or (np_ < pp and nd <= pd) else "跳变"
        kind = "回滚" if (nd < pd or (nd == pd and np_ < pp)) else "跳变"
        dd = nd - pd
        dp = np_ - pp
        dr = nr - pr
        print(f"  {b['aid']:<14}{b['seed']:>12}{f'{DAN_CN.get(pd,pd)}/{pp}/{pr}':>26}"
              f"{f'{DAN_CN.get(nd,nd)}/{np_}/{nr}':>26}    {kind} "
              f"(段{dd:+d} pt{dp:+d} R{dr:+.2f})")
    n_roll = sum(1 for b in breaks
                 if b["now"][0] < b["prev"][0]
                 or (b["now"][0] == b["prev"][0] and b["now"][1] < b["prev"][1]))
    print()
    print(f"  其中判定为【回滚】的: {n_roll} / {len(breaks)}")
    seeds = sorted({b["seed"] for b in breaks})
    print(f"  断裂发生的 seed: {seeds[:20]}{' ...' if len(seeds) > 20 else ''}")

print()
print("=" * 100)
print("按账号统计断裂次数")
print("=" * 100)
by = defaultdict(int)
for b in breaks:
    by[b["aid"]] += 1
for aid, n in sorted(by.items(), key=lambda kv: -kv[1]):
    print(f"  {aid:<16} {n:>4} 次")

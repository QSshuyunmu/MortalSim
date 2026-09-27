# -*- coding: utf-8 -*-
"""审计收尾：
  F3 房间违规分类 —— 区分【同桌内漂移，设计取舍】与【真·跨卓越界，Bug】
  F4 房间池饿死量化 —— 每卓合格人数 < 4 的时段，即"最低层被冻住"的风险
"""
import sqlite3, sys
from collections import defaultdict, Counter
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DAN_CN = {1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段", 6: "六段",
          7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"}


def official_room(dan, r):
    if dan >= 11:
        return "houou"
    if dan >= 7 and r >= 2000:
        return "houou"
    if dan >= 4 and r >= 1800:
        return "tokujou"
    if dan >= 1:
        return "joukyuu"
    return "ippan"


# 各卓的"硬性段位门槛"（与 R 无关的那一维）
DAN_GATE = {"houou": 7, "tokujou": 4, "joukyuu": 1, "ippan": 0}

con = sqlite3.connect("D:/tenhoulib/.diag/db_audit.db")
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT match_id, room, seed_idx, split, avatar_id, rank, dan_before, dan_after, "
    "rating_before, rating_after, pt_before, pt_after FROM ladder_games "
    "ORDER BY match_id ASC").fetchall()

print("=" * 100)
print("【F3】房间违规分类")
print("=" * 100)
per_avatar = defaultdict(list)
for r in rows:
    per_avatar[r["avatar_id"]].append(r)

run_start_viol, drift_viol, hard_viol = [], [], []
for aid, rs in per_avatar.items():
    prev_room = None
    for r in rs:
        room = r["room"]
        want = official_room(r["dan_before"], r["rating_before"])
        is_first_of_run = (room != prev_room)
        prev_room = room
        if room == want:
            continue
        # 顺序很重要：先判"进桌时就不合格"，否则会被段位维度吞掉
        if is_first_of_run:
            run_start_viol.append((aid, r, want))
        elif r["dan_before"] < DAN_GATE.get(room, 0):
            hard_viol.append((aid, r, want))
        else:
            drift_viol.append((aid, r, want))

print(f"  总违规行 1352，按【是否进桌时就已越界】分类：")
print(f"    (a) 进桌时就不合格 …… 真·越界（Bug）        {len(run_start_viol):>5} 行")
print(f"    (b) 进桌合格、中途段位掉下去 … 漂移-段位维度  {len(hard_viol):>5} 行")
print(f"    (c) 进桌合格、中途 R 漂过门槛 … 漂移-R维度    {len(drift_viol):>5} 行")

if run_start_viol:
    print()
    print("  (a) 真·越界明细:")
    for (got, want), n in Counter((x[1]["room"], x[2]) for x in run_start_viol).most_common():
        ex = [x for x in run_start_viol if x[1]["room"] == got and x[2] == want][:4]
        print(f"     {got:8s} ← 本应 {want:8s}: {n:4d} 行  例: "
              + ", ".join(f"{e[0]}({DAN_CN.get(e[1]['dan_before'])}/R{e[1]['rating_before']:.0f})"
                            for e in ex))
    sds = sorted({x[1]["seed_idx"] for x in run_start_viol})
    print(f"     涉及 seed: {sds[:10]}{' ...' if len(sds)>10 else ''}  （最大 {sds[-1]}）")
    print(f"     修复后 seed >= 300784 的: {sum(1 for x in run_start_viol if x[1]['seed_idx'] >= 300784)} 行")

if drift_viol:
    margins = []
    for aid, r, want in drift_viol:
        if r["room"] == "houou":
            margins.append(2000.0 - r["rating_before"])
        elif r["room"] == "tokujou":
            margins.append(1800.0 - r["rating_before"])
    margins.sort()
    print()
    print(f"  (c) 同桌内漂移的越界幅度分布（R 差多少才越线）:")
    print(f"     中位数 {margins[len(margins)//2]:.1f}  "
          f"P90 {margins[int(len(margins)*0.9)]:.1f}  最大 {margins[-1]:.1f}")
    print(f"     幅度 <= 30 的占 {sum(1 for m in margins if m <= 30)/len(margins)*100:.1f}%"
          f"  （一小局 R 的正常波动量级）")

print()
print("=" * 100)
print("【F4】房间池饿死量化：每个 半庄 时刻，各卓合格人数")
print("=" * 100)
# 逐半庄推进，用每行的 before 态统计"当下"各卓合格人数
state = {}
pool_hist = defaultdict(list)
for r in rows:
    state[r["avatar_id"]] = (r["dan_before"], r["rating_before"])
    if len(state) < 30:
        continue
    c = Counter(official_room(d, R) for d, R in state.values())
    for room in ("houou", "tokujou", "joukyuu"):
        pool_hist[room].append(c.get(room, 0))

for room in ("houou", "tokujou", "joukyuu"):
    h = pool_hist[room]
    if not h:
        continue
    starved = sum(1 for x in h if x < 4)
    print(f"  {room:8s} 池人数: 最小 {min(h)}  中位 {sorted(h)[len(h)//2]}  最大 {max(h)}"
          f"   |  不足4人(无法开桌)的时段占比 {starved/len(h)*100:5.1f}%")

print()
print("=" * 100)
print("【F4b】当前各卓人数 / 可开桌数")
print("=" * 100)
last = {}
for r in rows:
    last[r["avatar_id"]] = (r["dan_after"], r["pt_after"], r["rating_after"])
cur = Counter()
for aid, (d, pt, R) in last.items():
    cur[official_room(d, R)] += 1
print("  当前分布:", {k: v for k, v in cur.items()})
for room in ("joukyuu", "tokujou", "houou"):
    n = cur.get(room, 0)
    print(f"    {room:8s} {n:2d} 席  -> 可同时开桌数 {n//4} 张"
          + ("   ⚠ 不足 4 席，该卓无法开桌" if n < 4 else ""))

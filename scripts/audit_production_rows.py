# -*- coding: utf-8 -*-
"""逐行审计：对生产库每一行按【官方天凤规程】独立回算，与库中记录比对。

三道检查：
  A. 房间资格：该行账号当时的 (dan, R) 是否真的够格进这个卓？
  B. 计分正确：pt_after/dan_after 是否等于官方状态机从 before 态推出的值？
  C. Rating 正确：rating_after 是否符合官方公式？
  D. 卓隔离前提：同一 (seed, split) 的四行房间是否一致、四人是否互不相同？
"""
import sqlite3
import sys
from collections import defaultdict, Counter

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "D:/tenhoulib/.diag/db_audit.db"
ROOM_BONUS = {"houou": (90, 45, 0), "tokujou": (75, 30, 0),
              "joukyuu": (60, 15, 0), "ippan": (30, 15, 0)}
DAN_CN = {1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段", 6: "六段",
          7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"}


def official_room(dan, r):
    """官方门槛 → 该账号会去的最高合格卓"""
    if dan >= 11:
        return "houou"          # 天凤位：永久头衔，钉在凤凰
    if dan >= 7 and r >= 2000:
        return "houou"
    if dan >= 4 and r >= 1800:
        return "tokujou"
    if dan >= 1:
        return "joukyuu"
    return "ippan"


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
rows = con.execute(
    "SELECT match_id, room, seed_idx, split, seat, avatar_id, model_id, rank, "
    "pt_before, pt_after, dan_before, dan_after, rating_before, rating_after, table_avg_r "
    "FROM ladder_games ORDER BY match_id ASC").fetchall()
print(f"读取 {len(rows)} 行\n")

# 重建每个账号的场次计数（R 场数补正需要）
game_no = defaultdict(int)
bad_room, bad_pt, bad_r, bad_table = [], [], [], []
table_seats = defaultdict(list)

for r in rows:
    aid = r["avatar_id"]
    dan_b, pt_b, R_b = r["dan_before"], r["pt_before"], r["rating_before"]
    dan_a, pt_a, R_a = r["dan_after"], r["pt_after"], r["rating_after"]
    room, rank, avg_r = r["room"], r["rank"], r["table_avg_r"]
    game_no[aid] += 1
    n_games = game_no[aid]

    # --- A. 房间资格 ---
    want = official_room(dan_b, R_b)
    if room != want:
        bad_room.append((r["match_id"], aid, dan_b, R_b, room, want))

    # --- B. PT / 段位状态机 ---
    is_tenhou = (dan_b >= 11)
    e_pt, e_dan = pt_b, dan_b
    if not is_tenhou:
        if rank in (1, 2, 3):
            delta = ROOM_BONUS.get(room, ROOM_BONUS["tokujou"])[rank - 1]
        else:
            delta = -(15 * dan_b + 30)
        e_pt = pt_b + delta
        if e_dan == 10 and e_pt >= 4000:
            e_dan, e_pt = 11, 4000
        elif e_pt >= 400 * e_dan and e_dan < 10:
            e_dan += 1
            e_pt = 200 * e_dan
        elif e_pt < 0:
            if e_dan > 1:
                e_dan -= 1
                e_pt = 200 * e_dan
            else:
                e_pt = 200
    if (e_pt, e_dan) != (pt_a, dan_a):
        bad_pt.append((r["match_id"], aid, room, rank, dan_b, pt_b,
                       (pt_a, dan_a), (e_pt, e_dan)))

    # --- C. Rating 官方公式 ---
    pp = {1: 30.0, 2: 10.0, 3: -10.0, 4: -30.0}.get(rank, 0.0)
    corr = max(1.0 - 0.002 * n_games, 0.2)
    e_R = round(float(R_b) + (pp + (avg_r - R_b) / 40.0) * corr, 2)
    if abs(e_R - R_a) > 0.015:
        bad_r.append((r["match_id"], aid, R_b, R_a, e_R, n_games))

    table_seats[(r["seed_idx"], r["split"])].append((room, aid, r["seat"]))

# --- D. 每桌自洽性 ---
dup_seat, room_mix = [], []
for key, lst in table_seats.items():
    if len(lst) != 4:
        dup_seat.append((key, f"人数 {len(lst)}"))
        continue
    if len({x[1] for x in lst}) != 4:
        dup_seat.append((key, "同账号重复占座"))
    rooms = {x[0] for x in lst}
    if len(rooms) > 1:
        room_mix.append((key, rooms))

print("=" * 96)
print("【A】房间资格审计（该账号当时段位/R 是否够格进这一卓）")
print("=" * 96)
if not bad_room:
    print("  全部合格：没有任何账号在自己不够格的卓里打牌 ✓")
else:
    print(f"  ✗ {len(bad_room)} 行不合格（涉及 {len({x[1] for x in bad_room})} 个账号）")
    by_pair = Counter((x[4], x[5]) for x in bad_room)
    for (got, want), n in by_pair.most_common(12):
        ex = [x for x in bad_room if x[4] == got and x[5] == want][:3]
        print(f"    记录在 {got:8s} 但按门槛应为 {want:8s}：{n:5d} 行  例: "
              + ", ".join(f"{e[1]}({DAN_CN.get(e[2],e[2])}/R{e[3]:.0f})" for e in ex))
    seeds = sorted({x[0] for x in bad_room})
    print(f"    涉及 match_id 范围: 最早 {seeds[0]}, 最晚 {seeds[-1]}")

print()
print("=" * 96)
print("【B】PT/段位状态机审计（升段余剰切捨て / 降段重置 / 初段保底 / 天凤位）")
print("=" * 96)
if not bad_pt:
    print("  全部正确：每一行的 pt_after/dan_after 都等于官方状态机的推导值 ✓")
else:
    print(f"  ✗ {len(bad_pt)} 行不一致")
    for x in bad_pt[:15]:
        print(f"    match {x[0]} {x[1]} room={x[2]} rank={x[3]} "
              f"before={DAN_CN.get(x[4],x[4])}/{x[5]}pt  库={x[6]}  应为={x[7]}")

print()
print("=" * 96)
print("【C】Rating 官方公式审计")
print("=" * 96)
if not bad_r:
    print("  全部正确：rating_after = R + (顺位点 + (桌均R−自R)/40) × 场数补正 ✓")
else:
    print(f"  ✗ {len(bad_r)} 行不一致（前 10）")
    for x in bad_r[:10]:
        print(f"    match {x[0]} {x[1]} R {x[2]} -> 库{x[3]} 应为{x[4]} (第{x[5]}局)")

print()
print("=" * 96)
print("【D】卓隔离前提：每桌四人")
print("=" * 96)
if not dup_seat:
    print(f"  全部 {len(table_seats)} 桌均为 4 个互不相同的账号 ✓")
else:
    print(f"  ✗ {len(dup_seat)} 桌异常")
    for x in dup_seat[:10]:
        print(f"    {x[0]}: {x[1]}")
if not room_mix:
    print("  每桌四行的 room 字段完全一致 ✓")
else:
    print(f"  ✗ {len(room_mix)} 桌房间混杂")
    for x in room_mix[:5]:
        print(f"    {x[0]}: {x[1]}")

print()
print("=" * 96)
print("【E】账号终态与段位分布")
print("=" * 96)
last = {}
for r in rows:
    last[r["avatar_id"]] = (r["dan_after"], r["pt_after"], r["rating_after"], r["room"])
dist = Counter()
for aid, (d, pt, R, room) in sorted(last.items(), key=lambda kv: (-kv[1][0], -kv[1][1])):
    dist[DAN_CN.get(d, d)] += 1
    print(f"  {aid:16s} {DAN_CN.get(d,d):4s} {pt:5d}pt  R{R:7.2f}  [{room}]")
print()
print("  段位分布:", dict(dist))

print()
print("=" * 96)
print(f"审计总结：A房间资格 {len(bad_room)} 异常 / B计分 {len(bad_pt)} 异常 / "
      f"C Rating {len(bad_r)} 异常 / D桌自洽 {len(dup_seat)+len(room_mix)} 异常")
print("=" * 96)

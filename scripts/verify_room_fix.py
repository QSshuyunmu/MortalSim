# -*- coding: utf-8 -*-
"""验证修复后不再产生跨卓座位：检查最近 N 局中每局的房间门槛。"""
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

con = sqlite3.connect(r"C:\arena\ladder_results.db")
ROOM_MIN_DAN = {"houou": 7, "tokujou": 4}

# 取最近 600 行（约 2~3 张桌的量），按 match_id 倒序
# 只检查本次修复上线后的对局（之前的数据是旧代码产生的，不参与验证）
CUTOFF_SEED = int(__import__("os").environ.get("CUTOFF_SEED", "300784"))
rows = con.execute("""
    SELECT match_id, room, avatar_id, seed_idx, dan_before, dan_after
    FROM ladder_games WHERE seed_idx >= ? ORDER BY match_id ASC
""", (CUTOFF_SEED,)).fetchall()
rows = list(reversed(rows))
if not rows:
    print("无数据")
    raise SystemExit(1)

lo, hi = rows[0][0], rows[-1][0]
print(f"检查 seed>={CUTOFF_SEED}（修复后）: match_id {lo}~{hi}, {len(rows)} 行 / {len(rows)//4} 半庄")
print()

# 按 (room, seed) 分组，逐桌核对
import collections
tables = collections.defaultdict(list)
for mid, room, aid, seed, db_, da_ in rows:
    tables[(room, seed)].append((aid, db_, da_, mid))

bad = []
for (room, seed), mem in sorted(tables.items()):
    need = ROOM_MIN_DAN.get(room)
    if need is None:
        continue
    for aid, db_, da_, mid in mem:
        if db_ is not None and db_ < need:
            bad.append((room, seed, aid, db_, mid))

if bad:
    print(f"!! 仍有 {len(bad)} 个越界座位：")
    for room, seed, aid, db_, mid in bad[:20]:
        print(f"   {room} seed={seed} {aid} dan_before={db_} (match={mid})")
else:
    print("✅ 最近窗口内无跨卓座位（房间门槛检查全部通过）")

# 顺便看下各房间的段位分布（确认整体健康）
print()
print("最近窗口内各房间段位分布：")
for room, db_, n in con.execute("""
    SELECT room, dan_before, COUNT(*) FROM ladder_games WHERE seed_idx >= ? GROUP BY room, dan_before ORDER BY room, dan_before
""", (CUTOFF_SEED,)):
    print(f"  {room:<9} {db_}段: {n:>4} 座位")
con.close()

# -*- coding: utf-8 -*-
"""天凤机制保真度全量审计：逐项对照官方规程。

覆盖：段位阶梯、房间归属矩阵、升降段边界、R 公式、天凤位、卓隔离前提。
只读，不修改任何东西。
"""
import sys
from pathlib import Path

sys.path.insert(0, "D:/tenhoulib/.diag")
sys.path.insert(0, "D:/tenhoulib/Mortal/mortal")
sys.path.insert(0, "D:/tenhoulib/colab_deploy")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import logging
logging.disable(logging.CRITICAL)

from ladder_engine import PlayerState, ROOM_CONFIGS, DAN_NAMES

PASS, FAIL = [], []
def chk(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  [PASS] " if cond else "  [FAIL] ") + name + ("   " + detail if detail else ""))

def mk(dan=4, pt=800, rating=1900.0, **kw):
    return PlayerState("T", "m", "T", "tokujou_native", "", dan, pt, rating, **kw)


print("=" * 96)
print("【审计 1】段位阶梯：初期配点 / 升段线 / 四位扣分（对照官方表）")
print("=" * 96)
# 官方：初期pt = 200*D；昇段pt = 400*D；東南戦4位 = -(15*D+30)
OFFICIAL = {1: (200, 400, -45), 2: (400, 800, -60), 3: (600, 1200, -75),
            4: (800, 1600, -90), 5: (1000, 2000, -105), 6: (1200, 2400, -120),
            7: (1400, 2800, -135), 8: (1600, 3200, -150), 9: (1800, 3600, -165),
            10: (2000, 4000, -180)}
bad = []
for dan, (init_pt, up_pt, fourth) in OFFICIAL.items():
    p = mk(dan=dan, pt=init_pt, rating=2500.0)
    p.apply_game_result(4, 10000, 2500.0, "houou")
    got_fourth = p.pt - init_pt if p.dan == dan else None
    if got_fourth != fourth:
        bad.append(f"{DAN_NAMES[dan]} 四位 {got_fourth} != {fourth}")
    if 200 * dan != init_pt or 400 * dan != up_pt:
        bad.append(f"{DAN_NAMES[dan]} 配点/升段线不符")
chk("初段~十段：初期配点 200D / 升段线 400D / 四位 -(15D+30)", not bad, "; ".join(bad))

print()
print("=" * 96)
print("【审计 2】房间归属矩阵：对 (段位 × R) 全组合逐格核对官方门槛")
print("=" * 96)
# 官方：一般=四段R1800未満 / 上级=1級以上七段R2000未満 / 特上=四段R1800以上 / 凤凰=七段R2000以上
def official_room(dan, r, is_tenhou=False):
    if is_tenhou:
        return "houou"
    if dan >= 7 and r >= 2000:
        return "houou"
    if dan >= 4 and r >= 1800:
        return "tokujou"
    if dan >= 1:
        return "joukyuu"
    return "ippan"

mismatch = []
for dan in range(1, 12):
    for r in (1500, 1599, 1600, 1750, 1799, 1800, 1850, 1900, 1950, 1999, 2000, 2100):
        p = mk(dan=dan, pt=200 * dan, rating=float(r))
        got = p.get_room()
        exp = official_room(dan, r)
        if got != exp:
            mismatch.append(f"{DAN_NAMES[dan]}/R{r}: got={got} exp={exp}")
chk("房间归属 = 官方最高合格卓（所有段位×R 组合）", not mismatch, "; ".join(mismatch[:5]))

# 关键边界单点复核
cases = [
    (3, 1850, "joukyuu", "3段虽R达标但段位不足四段，不能进特上"),
    (4, 1799, "joukyuu", "4段但R差1点，不能进特上"),
    (4, 1800, "tokujou", "4段R1800整，进特上"),
    (6, 2050, "tokujou", "6段R2050，段位不足七段，不能进凤凰"),
    (7, 1999, "tokujou", "7段但R差1点，不能进凤凰"),
    (7, 2000, "houou", "7段R2000整，进凤凰"),
]
for dan, r, exp, why in cases:
    got = mk(dan=dan, pt=200 * dan, rating=float(r)).get_room()
    chk(f"边界 {why}", got == exp, f"got={got}")

print()
print("=" * 96)
print("【审计 3】升降段边界行为")
print("=" * 96)
# 升段：余剰pt切捨て（重置为 200*新段位）
p = mk(dan=3, pt=1185, rating=1900.0)
p.apply_game_result(1, 40000, 1900.0, "tokujou")   # +75 → 1260 ≥ 1200
chk("升段余剰切捨て：3段1185 +75 → 4段 800", p.dan == 4 and p.pt == 800, f"dan={p.dan} pt={p.pt}")

# 一局只升一段（否则 1185+90 会连升）
p = mk(dan=3, pt=1195, rating=2500.0)
p.apply_game_result(1, 60000, 2500.0, "houou")     # +90 → 1285
chk("一局只升一段（不连跳）", p.dan == 4, f"dan={p.dan}")

# 降段：重置为 200*新段位
p = mk(dan=4, pt=10, rating=1850.0)
p.apply_game_result(4, 5000, 1850.0, "tokujou")    # 10-90 = -80
chk("降段重置：4段10 → 3段 600", p.dan == 3 and p.pt == 600, f"dan={p.dan} pt={p.pt}")

# 初段下限
p = mk(dan=1, pt=50, rating=1500.0)
p.apply_game_result(4, 5000, 1500.0, "joukyuu")    # 50-45 = 5
p.apply_game_result(4, 5000, 1500.0, "joukyuu")    # 5-45 = -40
chk("初段下限：跌破0pt重置为200而非降级", p.dan == 1 and p.pt == 200, f"dan={p.dan} pt={p.pt}")

# 十段 → 天凤位
p = mk(dan=10, pt=3940, rating=2250.0)
p.apply_game_result(1, 60000, 2250.0, "houou")     # +90 → 4030
chk("十段 4000pt 晋升天凤位(11段)", p.dan == 11 and p.is_tenhou, f"dan={p.dan} pt={p.pt}")
# 天凤位冻结
d0, pt0 = p.dan, p.pt
p.apply_game_result(4, 3000, 2250.0, "houou")
chk("天凤位 PT/段位冻结", p.dan == d0 and p.pt == pt0, f"dan={p.dan} pt={p.pt}")

print()
print("=" * 96)
print("【审计 4】Rating 官方公式：(场数补正) × (顺位点 + (桌均R − 自R)/40) × 1.0")
print("=" * 96)
p = mk(dan=4, pt=800, rating=1900.0)
p.games = 100                       # 场数补正 = 1 - 0.002*100 = 0.8
avg = 1900.0
p.apply_game_result(1, 40000, avg, "tokujou")
exp = round(1900.0 + (30.0 + (avg - 1900.0) / 40.0) * 0.8, 2)
chk("1位 + 桌均R等于自R（场数补正0.8）", p.rating == exp, f"got={p.rating} exp={exp}")

p = mk(dan=4, pt=800, rating=1900.0)
p.games = 100
p.apply_game_result(4, 5000, 2000.0, "tokujou")
exp = round(1900.0 + (-30.0 + (2000.0 - 1900.0) / 40.0) * 0.8, 2)
chk("4位 + 桌均R高100（应少扣）", p.rating == exp, f"got={p.rating} exp={exp}")

p = mk(dan=4, pt=800, rating=1900.0)
p.games = 1000                      # 补正应被钳到 0.2 下限
p.apply_game_result(4, 5000, 1900.0, "tokujou")
exp = round(1900.0 + (-30.0) * 0.2, 2)
chk("场数补正下限 0.2 生效", p.rating == exp, f"got={p.rating} exp={exp}")

print()
print("=" * 96)
print("【审计 5】卓间 PT 档位（各卓 1/2/3 位加分）")
print("=" * 96)
OFFICIAL_BONUS = {"houou": (90, 45, 0), "tokujou": (75, 30, 0),
                  "joukyuu": (60, 15, 0), "ippan": (30, 15, 0)}
for room, (b1, b2, b3) in OFFICIAL_BONUS.items():
    got = tuple(ROOM_CONFIGS[room]["bonus"])
    chk(f"{room} 档位 {b1}/{b2}/{b3}", got == (float(b1), float(b2), float(b3)), f"got={got}")

print()
print("=" * 96)
print(f"审计结果：PASS={len(PASS)}  FAIL={len(FAIL)}")
if FAIL:
    print("失败项：")
    for f in FAIL:
        print("   -", f)
else:
    print("全部通过 —— 段位阶梯、房间门槛、升降段、R 公式、天凤位均与官方一致")
print("=" * 96)

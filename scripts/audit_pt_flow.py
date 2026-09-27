# -*- coding: utf-8 -*-
"""PT 总量溯源审计：宏观看 PT 从哪来、到哪去，并逐席对账。

天凤 PT 不是守恒量——桌内四人不是零和：
  桌内净额 = (本卓1位加分 + 本卓2位加分) - (15*段位 + 30)
    特上 四段: 75 + 30 - 90  = +15   <- 净生产
    特上 五段: 75 + 30 - 105 =   0   <- 中性
    特上 六段: 75 + 30 - 120 = -15   <- 净消耗
    凤凰 七段: 90 + 45 - 135 =   0
    凤凰 八段: 90 + 45 - 150 = -15
    凤凰 九段: 90 + 45 - 165 = -30
    凤凰 十段: 90 + 45 - 180 = -45
    上级 三段: 60 + 15 -  75 =   0

另有三个"非对局"出入口：
  升段余剰切捨て -> 摧毁 PT（官方规程：昇段時の余剰ptは切り捨て）
  降段重置为初期pt -> 注入 PT（官方规程：降段も初期ptからスタート）
  回收席位/新席入场 -> 旧席 PT 随席离场、新席注入 200*4=800
  状态链断裂（历史 bug）-> PT 凭空出现/消失，本审计会把它们逐条抓出来

用法：python audit_pt_flow.py
"""
import json
import sqlite3
import sys
from collections import defaultdict

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DB = "C:/arena/ladder_results.db"
STATE = "C:/arena/ladder_state.json"
ROOM_PT = {"houou": (90, 45, 0), "tokujou": (75, 30, 0),
           "joukyuu": (60, 15, 0), "ippan": (30, 15, 0)}
ROOM_CN = {"houou": "凤凰", "tokujou": "特上", "joukyuu": "上级", "ippan": "一般"}
DAN_CN = {1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段", 6: "六段",
          7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"}


def game_net(room, rank, dan_before):
    """本局按官方档位的纯对局增减（不含升/降段重置）。"""
    if rank in (1, 2, 3):
        return ROOM_PT.get(room, ROOM_PT["tokujou"])[rank - 1]
    if rank == 4:
        return -(15 * dan_before + 30)
    return 0


con = sqlite3.connect(DB, timeout=30)
con.row_factory = sqlite3.Row
rows = list(con.execute(
    "SELECT match_id, room, seed_idx, avatar_id, model_id, rank, dan_before, dan_after, "
    "pt_before, pt_after FROM ladder_games ORDER BY match_id"))
state = json.loads(open(STATE, encoding="utf-8").read())["players"]
roster = {r[0]: {"retired_seed": r[1], "gen": r[2], "parent": r[3]}
          for r in con.execute("SELECT avatar_id, retired_seed, gen, parent_id FROM ladder_roster")}

print("=" * 104)
print("【A】逐席 PT 对账：当前 PT 是否等于「初始配点 + 逐局增减之和」")
print("=" * 104)
per = defaultdict(lambda: {"init": None, "sum_net": 0, "sum_reset": 0, "n": 0,
                           "destroyed_promo": 0, "injected_demo": 0,
                           "last_pt": None, "first_pt": None, "resets": 0})
for r in rows:
    a = r["avatar_id"]
    d = per[a]
    if d["init"] is None:
        d["init"] = int(r["pt_after"]) - (int(r["pt_after"]) - int(r["pt_before"]))  # 首局前的 pt
        d["init"] = int(r["pt_before"])
    d["n"] += 1
    delta = int(r["pt_after"]) - int(r["pt_before"])
    net = game_net(r["room"], int(r["rank"]), int(r["dan_before"]))
    d["sum_net"] += net
    reset = delta - net
    if reset:
        d["sum_reset"] += reset
        d["resets"] += 1
        if int(r["dan_after"]) > int(r["dan_before"]):
            d["destroyed_promo"] += -reset if reset < 0 else 0
        elif int(r["dan_after"]) < int(r["dan_before"]):
            d["injected_demo"] += reset if reset > 0 else 0
    d["last_pt"] = int(r["pt_after"])
    if d["first_pt"] is None:
        d["first_pt"] = int(r["pt_before"])

bad = []
print("%-14s %-6s %9s %9s %10s %7s %11s %11s" %
      ("账号", "世代", "初始pt", "逐局净额", "重置净额", "重置次数", "应得pt", "实际pt"))
print("-" * 104)
tot_recon_diff = 0
for a, d in sorted(per.items(), key=lambda kv: -abs(kv[1]["sum_reset"])):
    expect = d["init"] + d["sum_net"] + d["sum_reset"]
    actual = d["last_pt"]
    diff = actual - expect
    tot_recon_diff += diff
    g = roster.get(a, {})
    mark = "" if diff == 0 else "   <<< 差异 %+d" % diff
    if diff:
        bad.append((a, diff, d))
    if diff or abs(d["sum_reset"]) > 400:
        print("%-14s %-6s %9d %9d %10d %7d %11d %11d%s" %
              (a, str(g.get("gen", 1)), d["init"], d["sum_net"], d["sum_reset"],
               d["resets"], expect, actual, mark))
print()
print("对账不平的席位：%d 个，合计差异 %+d pt" % (len(bad), tot_recon_diff))

print()
print("=" * 104)
print("【B】PT 产出/消耗分解：谁在生产、谁在消耗")
print("=" * 104)
cell = defaultdict(lambda: {"n": 0, "net": 0})
for r in rows:
    k = (r["room"], int(r["dan_before"]))
    c = cell[k]
    c["n"] += 1
    c["net"] += game_net(r["room"], int(r["rank"]), int(r["dan_before"]))
print("%-10s %-8s %9s %14s %14s   %s" % ("卓", "段位", "局数", "桌内净额(总)", "每局净额", "性质"))
print("-" * 104)
gnet = 0
for (room, dan), c in sorted(cell.items(), key=lambda kv: (kv[0][0], kv[0][1])):
    per_game = c["net"] / c["n"]
    gnet += c["net"]
    kind = ("生产" if c["net"] > 0 else ("消耗" if c["net"] < 0 else "中性"))
    print("%-10s %-8s %9d %14d %14.2f   %s%s" %
          (ROOM_CN.get(room, room), DAN_CN.get(dan, dan), c["n"], c["net"], per_game,
           kind, "" if per_game == 0 else ""))
print("-" * 104)
print("对局产生的 PT 净额合计: %+d" % gnet)

print()
print("=" * 104)
print("【C】非对局出入口")
print("=" * 104)
d_promo = sum(d["destroyed_promo"] for d in per.values())
d_demo = sum(d["injected_demo"] for d in per.values())
# sum_reset 是净额（-摧毁+注入），先还原成净额再减去升降段两部分，才是真·其它
d_other = sum(d["sum_reset"] for d in per.values()) - (-d_promo + d_demo)
retired_pt = sum(int(state[a]["pt"]) for a in state if state[a].get("retired"))
retired_n = sum(1 for a in state if state[a].get("retired"))
newseats = [a for a in state if roster.get(a, {}).get("gen", 1) > 1]
new_pt = sum(200 * 4 for _ in newseats)
print("  升段余剰切捨て（摧毁）      : %+d" % -d_promo)
print("  降段重置为初期pt（注入）    : %+d" % d_demo)
print("  其它重置（初段保底等）      : %+d" % d_other)
print("  两条合计（重置净额）        : %+d" % (-d_promo + d_demo + d_other))
print("  回收席位随席离场（移出在用池）: %+d  （%d 席）" % (-retired_pt, retired_n))
print("  新席入场注入 800*%d          : %+d （已计入各席首局前配点，不另加）"
      % (len(newseats), new_pt))
print("  状态链断裂造成的凭空增减    : %+d   <- 历史 bug 的 PT 足迹" % tot_recon_diff)

print()
print("=" * 104)
print("【D】守恒恒等式")
print("=" * 104)
# 口径：把「在用 + 已回收」看成一个整体池。初始配点已包含新席入场时注入的
# 800/席（各席首局前的配点就是它的入场值），故不再单独加，否则会重复计入。
cur_active = sum(int(v["pt"]) for v in state.values() if not v.get("retired"))
cur_all = sum(int(v["pt"]) for v in state.values())
init_total = sum(d["init"] for d in per.values())
neta = sum(d["sum_reset"] for d in per.values())
lhs = init_total + gnet + neta + tot_recon_diff
print("  【在用 + 已回收】当前 PT 总和 = %+d  （在用 %d / 已回收 %d）"
      % (cur_all, cur_active, cur_all - cur_active))
print("  = 初始配点总和（各席首局前）  %+d" % init_total)
print("  + 对局净额                    %+d" % gnet)
print("  + 重置净额（升段摧毁/降段注入）%+d" % neta)
print("  + 状态链断裂凭空增减          %+d" % tot_recon_diff)
print("  ----------------------------------------")
print("  推算值                        = %+d" % lhs)
print("  实际值                        = %+d" % cur_all)
print("  残差                          = %+d   %s"
      % (cur_all - lhs, "✓ 平" if cur_all - lhs == 0 else "✗ 不平"))

# -*- coding: utf-8 -*-
"""天梯全量榜单 -> QQ 群推送（每 3 小时一次）。

与旧的混战池推送的区别：旧的是从已经停跑的混战池牌谱语料重算，每 3 小时重发
同一份冻结快照；本脚本读的是当前在跑的天凤四卓天梯的实时库。

数据流（由 ladder_push.ps1 串起来，沿用旧推送器"远端出数据/本机发送"的分工）：
  Atozuke: ladder_stats_export.py 读 ladder_results.db -> _ladder_stats.tsv
  scp 回本机 -> ladder_stats.tsv -> 本脚本格式化 -> POST 到本机 OneBot

用法：python -X utf8 ladder_push.py [--tsv D:/tenhoulib/.diag/ladder_stats.tsv]
                                   [--dry-run]
"""
import argparse
import datetime
import json
import sys
import urllib.request
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

GROUP_ID = 1063781373
ONEBOT = "http://127.0.0.1:5700/send_group_msg"
MEDAL = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
DAN = {1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段", 6: "六段",
       7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位"}


def pct(x):
    return "%.1f%%" % (x * 100)


def build(rows, now):
    tot = sum(int(r["games"]) for r in rows)
    seats = sum(int(r["seats"]) for r in rows)
    rec = sum(int(r["recycled"]) for r in rows)
    h = sum(int(r["games_houou"]) for r in rows)
    t = sum(int(r["games_tokujou"]) for r in rows)
    out = ["【Atozuke 天凤四卓天梯 · 全量榜单】%s" % now,
           "官方档位 PT｜特上 +75/+30/0｜凤凰 +90/+45/0｜四位 -(15×段位+30)",
           "按物理模型聚合（同权重分身合并，样本量才是这个模型的真实水平）", ""]
    for i, r in enumerate(rows):
        n = max(1, int(r["games"]))
        r1, r2, r3, r4 = (int(r["r1"]), int(r["r2"]), int(r["r3"]), int(r["r4"]))
        avg = (r1 + 2 * r2 + 3 * r3 + 4 * r4) / n
        rd = int(r["rounds"])
        seg = []
        if int(r["dan_max"]):
            hi = DAN.get(int(r["dan_max"]), str(r["dan_max"]))
            lo = DAN.get(int(r["dan_min"]), str(r["dan_min"]))
            seg.append("现段位 %s~%s" % (hi, lo))
        seg.append("特%d 凤%d" % (int(r["games_tokujou"]), int(r["games_houou"])))
        if rd:
            seg.append("和%s 铳%s 立%s 副露%s" % (
                pct(int(r["agari"]) / rd), pct(int(r["houjuu"]) / rd),
                pct(int(r["riichi"]) / rd), pct(int(r["fuuro"]) / rd)))
        tag = "（含回收 %d 席）" % int(r["recycled"]) if int(r["recycled"]) else ""
        out.append("%s %s  %d席 %d半庄  R均%.0f%s"
                   % (MEDAL[i] if i < len(MEDAL) else "(%d)" % (i + 1),
                      r["model"], int(r["seats"]), n, float(r["r_avg"]), tag))
        out.append("   1位%s 2位%s 3位%s 4位%s · 均位 %.3f"
                   % (pct(r1 / n), pct(r2 / n), pct(r3 / n), pct(r4 / n), avg))
        out.append("   " + " · ".join(seg))
        out.append("")
    out.append("—— %d席在位 + %d席已回收 · 合计 %d半庄（特%d 凤%d）· %s"
               % (seats - rec, rec, tot, t, h, datetime.datetime.now().strftime("%m-%d %H:%M")))
    out.append("注: 顺位为逐半庄口径；和/铳/立直/副露为逐局口径（与 libriichi Stat 一致）")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", default="D:/tenhoulib/.diag/ladder_stats.tsv")
    ap.add_argument("--dry-run", action="store_true", help="只打印不发送")
    ap.add_argument("--group", type=int, default=GROUP_ID)
    a = ap.parse_args()

    p = Path(a.tsv)
    if not p.is_file():
        print("[fatal] 找不到 %s（远端导出或 scp 失败）" % p)
        return 1
    lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(lines) < 2:
        print("[fatal] %s 无数据行" % p)
        return 1
    hdr = lines[0].split("\t")
    rows = [dict(zip(hdr, l.split("\t"))) for l in lines[1:]]
    msg = build(rows, datetime.datetime.now().strftime("%m-%d %H:%M"))

    if a.dry_run:
        print(msg)
        print("\n[dry-run] %d 款模型，%d 字符" % (len(rows), len(msg)))
        return 0

    data = json.dumps({"group_id": a.group, "message": msg}).encode()
    req = urllib.request.Request(ONEBOT, data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            st = json.loads(r.read().decode()).get("status")
    except Exception as e:
        print("[fatal] 发送失败: %s: %s" % (type(e).__name__, str(e)[:160]))
        return 1
    print("QQ: %s | chars %d | models %d" % (st, len(msg), len(rows)))
    return 0


if __name__ == "__main__":
    sys.exit(main())

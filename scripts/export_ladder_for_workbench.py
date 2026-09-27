#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""天梯 SQLite → keqing1-workbench 榜单 UI 数据转换器（纯标准库）。

产出（schema 严格对齐 workbench/replay/ladder.py 的加载器）：
  <data_root>/ladder/registries/<season_id>.json          赛季注册表（keqing.ladder.season.v1）
  <data_root>/ladder/seasons/<season_id>/snapshots/latest/
      account_summary.json                                keqing.mortal.platform_account_report.v2
      account_ledger.jsonl                                逐场账本（transition ∈ none/promotion/demotion/tenhou）
      rating_curve.csv                                    rating/pt 曲线（loader 自动降采样到 240 点）

字段来源：
  * 聚合统计（games / rank_1..4）← ladder_games 全量（事实源）
  * 段位 / PT / Rating / 天凤位 ← ladder_state.json（runner 每 5 批 + 收尾时写出的精确快照）
  * 逐场 transition / pt_delta / rating 序列 ← ladder_games 的簿记列
    （pt_before/pt_after/dan_before/dan_after/rating_before/rating_after；旧库无此列时相关行降级跳过）

用法：
  python export_ladder_for_workbench.py --db ... --state ... --config ... --data-root ... [--season-id ...]
  或作为模块被 ladder_arena_atozuke.py 调用：export_all(db=..., state=..., config=..., data_root=...)
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sqlite3
from collections import defaultdict
from pathlib import Path

# ---- rank 词表（与 keqing1-workbench rank_systems/tenhou.py 完全一致）----
RANK_NAMES_CN = {
    1: "初段", 2: "二段", 3: "三段", 4: "四段", 5: "五段",
    6: "六段", 7: "七段", 8: "八段", 9: "九段", 10: "十段", 11: "天凤位",
}
ROOM_PT = {  # 半庄正位 PT（与 ladder_engine.ROOM_CONFIGS 一致；3 位恒 0）
    "houou": (90, 45, 0),
    "tokujou": (75, 30, 0),
    "joukyuu": (60, 15, 0),
    "ippan": (30, 15, 0),
}

SEASON_SCHEMA = "keqing.ladder.season.v1"
REPORT_SCHEMA = "keqing.mortal.platform_account_report.v2"


def rank_id_of(dan: int) -> str:
    return "tenhou" if dan >= 11 else f"{int(dan)}dan"


def rank_ordinal_of(dan: int) -> int:
    return 21 if dan >= 11 else 10 + int(dan)


def pt_target_of(dan: int):
    return None if dan >= 11 else 400 * int(dan)


def transition_of(dan_before: int, dan_after: int) -> str:
    if dan_before < 10 <= dan_after:
        return "tenhou"          # 十段登顶天凤位
    if dan_after > dan_before:
        return "promotion"
    if dan_after < dan_before:
        return "demotion"
    return "none"


def room_of(dan: int, rating) -> str:
    """天凤双门槛：凤凰(7段+R2000) / 特上(4段+R1800) / 其余上级。"""
    if dan >= 7 and (rating or 0) >= 2000:
        return "houou"
    if dan >= 4 and (rating or 0) >= 1800:
        return "tokujou"
    return "joukyuu"


def _stable_dan_room(aid: str, room: str, room_agg: dict,
                     min_games: int = 100, min_r4: int = 25):
    """单个卓别的安定段位（天凤官方「段位相当」口径）。

    官方定义（系数即该卓的 PT 结构）：
      鳳凰 = ((１位*60 + ２位*30)/４位 - 20)/10 = (6*r1 + 3*r2)/r4 - 2
      特上 = ((１位*50 + ２位*20)/４位 - 20)/10 = (5*r1 + 2*r2)/r4 - 2
    注意 `- 2` 不能漏（等价于分子 -20 后再 /10）。

    只取【该卓内】的对局：两个卓的系数与对手强度都不同，跨卓混算会把两套
    口径搅在一起，得到没有意义的数。

    样本门槛 min_games=100 且 min_r4=25：本估计以 r4 为分母，r4 的泊松相对
    标准误约 1/sqrt(r4)，r4=12 时误差可达 ±3.5 段（纯噪声，实测有账号因此
    虚高到 12.25）。门槛以下返回 None，宁可留空也不给误导性的数字。
    """
    ra = (room_agg.get(aid) or {}).get(room) or {}
    if ra.get("games", 0) < min_games or (ra.get("r4") or 0) < min_r4:
        return None
    a, b = (6.0, 3.0) if room == "houou" else (5.0, 2.0)
    return round((a * ra["r1"] + b * ra["r2"]) / ra["r4"] - 2.0, 2)


def _atomic_write(path: Path, data: str) -> None:
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    os.replace(tmp, path)


def export_all(db_path, state_path, config_path, data_root,
               season_id: str = "atozuke-ladder-v1",
               title: str = "Atozuke 四卓分层天梯") -> dict:
    db_path = Path(db_path)
    config_path = Path(config_path)
    data_root = Path(data_root)

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    phys = {pm["model_id"]: pm for pm in cfg.get("physical_models", [])}
    avatars = cfg.get("avatars", [])

    state = {}
    if state_path and Path(state_path).is_file():
        try:
            state = json.loads(Path(state_path).read_text(encoding="utf-8")).get("players", {})
        except Exception:
            state = {}

    # ---- 读库：聚合 + 逐场簿记 ----
    con = sqlite3.connect(str(db_path), timeout=30)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(ladder_games)")}
        has_bk = {"pt_before", "pt_after", "dan_before", "dan_after",
                  "rating_after"} <= cols
        sel = ("SELECT match_id, room, avatar_id, model_id, rank, score"
               + (", pt_before, pt_after, dan_before, dan_after, rating_before, rating_after"
                  if has_bk else "")
               + " FROM ladder_games ORDER BY match_id")
        agg = {a["avatar_id"]: {"games": 0, "r1": 0, "r2": 0, "r3": 0, "r4": 0,
                                "pt_delta_sum": 0, "bk_games": 0,
                                "promotions": 0, "demotions": 0,
                                "max_dan": 0, "game_idx": 0}
               for a in avatars}
        ledger_rows = defaultdict(list)
        curve_rows = defaultdict(list)
        # 逐局统计（和/铳/副露/立直 per-round 口径），由 runner 累计落盘
        pstats = {}
        try:
            with sqlite3.connect(str(db_path), timeout=30) as c2:
                has_ps = {r[1] for r in c2.execute("PRAGMA table_info(player_stats)")}
                if "agari" in has_ps:
                    for aid2, g2, rd2, ag2, hj2, fu2, rc2 in c2.execute(
                            "SELECT avatar_id, games, rounds, agari, houjuu, fuuro, riichi FROM player_stats"):
                        pstats[aid2] = {"games": g2, "rounds": rd2, "agari": ag2,
                                        "houjuu": hj2, "fuuro": fu2, "riichi": rc2}
        except Exception:
            pstats = {}
        db_current = {}   # avatar_id -> (dan, pt, rating) 最后一局簿记
        room_agg = {}     # avatar_id -> room -> {games,r1..r4}（安定段位按卓分别算）
        total_games = 0
        for row in con.execute(sel):
            total_games += 1
            (_mid, room, aid, _model, rank, _score) = row[:6]
            g = agg.setdefault(aid, {"games": 0, "r1": 0, "r2": 0, "r3": 0, "r4": 0,
                                     "pt_delta_sum": 0, "bk_games": 0,
                                     "promotions": 0, "demotions": 0,
                                     "max_dan": 0, "game_idx": 0})
            g["games"] += 1
            g[f"r{int(rank)}"] += 1
            _ra = room_agg.setdefault(aid, {}).setdefault(
                room, {"games": 0, "r1": 0, "r2": 0, "r3": 0, "r4": 0})
            _ra["games"] += 1
            _ra[f"r{int(rank)}"] += 1
            if not has_bk:
                continue
            (pt_b, pt_a, dan_b, dan_a, r_b, r_a) = row[6:12]
            if pt_b is None or pt_a is None or dan_b is None or dan_a is None \
                    or r_a is None:
                continue  # 旧数据无簿记，降级跳过（仅计入聚合）
            db_current[aid] = (int(dan_a), int(pt_a), float(r_a))
            tr = transition_of(int(dan_b), int(dan_a))
            if tr == "promotion":
                g["promotions"] += 1
            elif tr == "demotion":
                g["demotions"] += 1
            g["pt_delta_sum"] += int(pt_a) - int(pt_b)
            g["bk_games"] += 1
            g["max_dan"] = max(g["max_dan"], int(dan_a))
            g["game_idx"] += 1
            gid = g["game_idx"]
            rid_a = rank_id_of(dan_a)
            ledger_rows[aid].append({
                "account_id": aid,
                "game_index": gid,
                "rank": int(rank),
                "final_score": int(_score),
                "score_delta": None,
                "game_length": "hanchan",
                "pt_tier": room,
                "positive_pt": list(ROOM_PT.get(room, (0, 0, 0))),
                "rank_before": rank_id_of(dan_b),
                "pt_before": int(pt_b),
                "pt_delta": int(pt_a) - int(pt_b),
                "transition": tr,
                "rank_after": rid_a,
                "pt_after": int(pt_a),
                "rating_before": (float(r_b) if r_b is not None else None),
                "rating_after": float(r_a),
                "source_log": None,
            })
            curve_rows[aid].append([
                gid, aid, _model, f"{float(r_a):.2f}", int(pt_a),
                rid_a, RANK_NAMES_CN.get(int(dan_a), ""), rank_id_of(dan_b),
                rid_a, tr,
                ("" if pt_target_of(dan_a) is None else str(pt_target_of(dan_a))),
                g["games"],
            ])
    finally:
        con.close()

    # ---- 赛季注册表 ----
    models_out = []
    for pm in cfg.get("physical_models", []):
        mid = pm["model_id"]
        accs = [{"account_id": a["avatar_id"], "display_name": a["display_name"]}
                for a in avatars if a["model_id"] == mid]
        if not accs:
            continue
        models_out.append({
            "model_id": mid,
            "checkpoint": f"models/{pm.get('file', mid + '.pth')}",
            "accounts": accs,
        })

    report_dir_rel = f"seasons/{season_id}/snapshots/latest"
    registry = {
        "schema": SEASON_SCHEMA,
        "season_id": season_id,
        "title": title,
        "status": "running",
        "default": True,
        "report_dir": report_dir_rel,
        "scoring": {
            "system": "tenhou_rank_progression",
            "version": "atozuke-ladder-v1",
            "game_length": "hanchan",
            "initial_rank": "7dan",
            "initial_rating": 2100,
            "notes": "各账号初始段位/PT/R 不同（权威状态在 ladder_state.json）；"
                     "凤凰90/45/0、特上75/30/0、上级60/15/0，四位 -(15D+30)；"
                     "十段满 4000PT 晋天凤位。",
        },
        "models": models_out,
        "notes": "由 export_ladder_for_workbench.py 从 Atozuke 天梯 DB 自动生成。",
    }

    # ---- account_summary.json ----
    summary_accounts = []
    for a in avatars:
        aid = a["avatar_id"]
        g = agg.get(aid, {"games": 0, "r1": 0, "r2": 0, "r3": 0, "r4": 0,
                          "pt_delta_sum": 0, "bk_games": 0, "promotions": 0,
                          "demotions": 0, "max_dan": 0})
        # 状态源优先级：DB 簿记最后一局（事实源）> state 快照 > config 初始
        s = state.get(aid, {})
        if aid in db_current:
            dan, pt, rating = db_current[aid]
        else:
            dan = int(s.get("dan") or a.get("init_dan") or 1)
            pt = s.get("pt")
            if pt is None:
                pt = a.get("init_pt")
            rating = s.get("rating")
            if rating is None:
                rating = a.get("init_rating")
        is_tenhou = bool(s.get("is_tenhou")) or dan >= 11
        ps = pstats.get(aid) or {}
        agari_rate = houjuu_rate = fuuro_rate = riichi_rate = None
        if ps and ps.get("rounds"):
            agari_rate = ps["agari"] / ps["rounds"]
            houjuu_rate = ps["houjuu"] / ps["rounds"]
            fuuro_rate = ps["fuuro"] / ps["rounds"]
            riichi_rate = ps["riichi"] / ps["rounds"]
        rid = rank_id_of(dan)
        target = pt_target_of(dan)
        pt_cur = float(pt) if pt is not None else 0.0
        games = g["games"]
        avg_rank = ((g["r1"] + 2 * g["r2"] + 3 * g["r3"] + 4 * g["r4"]) / games
                    if games else None)
        highest_dan = max(g["max_dan"], dan)
        summary_accounts.append({
            "account_id": aid,
            "model_label": a["model_id"],
            "games": games,
            "rank_id": rid,
            "rank_name": RANK_NAMES_CN.get(dan, str(dan)),
            "rank_ordinal": rank_ordinal_of(dan),
            "pt_current": pt_cur,
            "pt_target": target,
            "pt_progress": (round(pt_cur / target, 4) if target else None),
            "promotions": g["promotions"],
            "demotions": g["demotions"],
            "highest_rank_id": rank_id_of(highest_dan),
            "highest_rank_name": RANK_NAMES_CN.get(highest_dan, str(highest_dan)),
            # 特/凤局数分列（让读者看清每个安定段背后的样本量）
            "games_houou": (room_agg.get(aid, {}).get("houou", {}) or {}).get("games", 0),
            "games_tokujou": (room_agg.get(aid, {}).get("tokujou", {}) or {}).get("games", 0),
            # 特/凤安定分卓计算：各卓用各自公式与各自对局
            "stable_dan_houou": _stable_dan_room(aid, "houou", room_agg),
            "stable_dan_tokujou": _stable_dan_room(aid, "tokujou", room_agg),
            "stable_dan": _stable_dan_room(aid, room_of(dan, rating), room_agg),
            "tenhou_reached": is_tenhou,
            "total_pt_delta": (g["pt_delta_sum"] if g["bk_games"] else None),
            "avg_pt_delta": (round(g["pt_delta_sum"] / g["bk_games"], 3)
                             if g["bk_games"] else None),
            "rating": (float(rating) if rating is not None else 0.0),
            "rank_1": g["r1"], "rank_2": g["r2"], "rank_3": g["r3"], "rank_4": g["r4"],
            "avg_rank": (round(avg_rank, 4) if avg_rank is not None else None),
            "avg_rank_pt": None,
            # 四项细 stats 本期无牌谱统计源，置空（前端 null-safe 显示 —）
            "agari_rate": agari_rate, "houjuu_rate": houjuu_rate,
            "fuuro_rate": fuuro_rate, "riichi_rate": riichi_rate,
            "stats_games": ps.get("rounds"),
            "stats_coverage": (ps["games"] / games if ps and games else None),
        })

    summary = {
        "schema": REPORT_SCHEMA,
        "games": total_games,
        "scoring": registry["scoring"],
        "accounts": summary_accounts,
    }

    # ---- 落盘（原子替换）----
    reg_dir = data_root / "ladder" / "registries"
    snap_dir = data_root / "ladder" / "seasons" / season_id / "snapshots" / "latest"
    reg_dir.mkdir(parents=True, exist_ok=True)
    snap_dir.mkdir(parents=True, exist_ok=True)

    _atomic_write(reg_dir / f"{season_id}.json",
                  json.dumps(registry, ensure_ascii=False, indent=1))
    _atomic_write(snap_dir / "account_summary.json",
                  json.dumps(summary, ensure_ascii=False, indent=1))

    ledger_lines = []
    for aid in sorted(ledger_rows):
        for r in ledger_rows[aid]:
            ledger_lines.append(json.dumps(r, ensure_ascii=False))
    _atomic_write(snap_dir / "account_ledger.jsonl", "\n".join(ledger_lines) + "\n")

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["game_index", "account_id", "model_label", "rating", "pt",
                "rank_id", "rank_name", "rank_before", "rank_after", "transition",
                "pt_target", "games"])
    for aid in sorted(curve_rows):
        for r in curve_rows[aid]:
            w.writerow(r)
    _atomic_write(snap_dir / "rating_curve.csv", buf.getvalue())

    return {"accounts": len(summary_accounts), "games": total_games,
            "ledger_rows": sum(len(v) for v in ledger_rows.values()),
            "snapshot_dir": str(snap_dir)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--season-id", default="atozuke-ladder-v1")
    a = ap.parse_args()
    info = export_all(a.db, a.state, a.config, a.data_root, a.season_id)
    print(f"[export] {info['accounts']} 席 / {info['games']} 局 / "
          f"ledger {info['ledger_rows']} 行 -> {info['snapshot_dir']}")


if __name__ == "__main__":
    main()

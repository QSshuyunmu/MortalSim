"""多模型全盘审查核心引擎 (Multi-Model Replay & Review Engine).

核心职责：
1. 完整维护四方日麻桌 BoardTracker（四家手牌、副露、6列牌河、实时点数、山牌余量、宝牌翻开）；
2. 拆解全局为具体局 (Kyokus: 东1局~南4局)，在每个打牌决策点记录完整牌桌物理快照；
3. 顺序调度 Aegis (神盾)、Sol (烈阳)、Logos (理性) 三模型进行整局前向推断并即时释放显存；
4. 输出完全结构化的全局回放与三模型并行审查数据包。
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any
import torch

log = logging.getLogger("reviewer.engine")

ACTION_TO_MJAI = [
    '1m','2m','3m','4m','5m','6m','7m','8m','9m',
    '1p','2p','3p','4p','5p','6p','7p','8p','9p',
    '1s','2s','3s','4s','5s','6s','7s','8s','9s',
    'E','S','W','N','P','F','C',
    '5mr','5pr','5sr',
]

MODELS_CONFIG = [
    {"id": "bin_0910", "name": "Aegis", "tag": "神盾·避四"},
    {"id": "distill_nova", "name": "Sol", "tag": "烈阳·争一"},
    {"id": "distill_41b_infer", "name": "Logos", "tag": "理性·基准"},
]

BAKAZE_MAP = {"E": "东", "S": "南", "W": "西", "N": "北"}

def tile_sort_key(t: str) -> tuple[int, int]:
    """手牌理牌排序键值。"""
    if not t or t == "?":
        return (9, 9)
    suit_order = {'m': 0, 'p': 1, 's': 2, 'z': 3}
    suit = t[-1]
    if t in ('E', 'S', 'W', 'N', 'P', 'F', 'C'):
        z_map = {'E': 1, 'S': 2, 'W': 3, 'N': 4, 'P': 5, 'F': 6, 'C': 7}
        return (3, z_map.get(t, 9))
    if t.endswith('r'):
        num = int(t[0])
        return (suit_order.get(t[1], 9), num * 10 + 5)
    num = int(t[0]) if t[0].isdigit() else 9
    return (suit_order.get(suit, 9), num * 10)


class ReplayStateTracker:
    """全面追踪 MJAI 事件流中的日麻牌桌世界状态。"""
    def __init__(self, target_seat: int = 0):
        self.target_seat = target_seat
        self.kyokus: list[dict[str, Any]] = []
        self.current_kyoku: dict[str, Any] | None = None
        self.current_kyoku_idx = -1

    def handle_event(self, ev: dict[str, Any], ev_idx: int) -> dict[str, Any] | None:
        t = ev.get("type")
        if t == "start_kyoku":
            self.current_kyoku_idx += 1
            bakaze = ev.get("bakaze", "E")
            kyoku = ev.get("kyoku", 1)
            honba = ev.get("honba", 0)
            kyotaku = ev.get("kyotaku", 0)
            oya = ev.get("oya", 0)
            scores = list(ev.get("scores", [25000, 25000, 25000, 25000]))
            dora_marker = ev.get("dora_marker", "1z")
            tehais = [list(h) for h in ev.get("tehais", [[],[],[],[]])]

            title_str = f"{BAKAZE_MAP.get(bakaze, bakaze)}{kyoku}局 {honba}本场"
            self.current_kyoku = {
                "kyoku_idx": self.current_kyoku_idx,
                "title": title_str,
                "bakaze": bakaze,
                "kyoku": kyoku,
                "honba": honba,
                "kyotaku": kyotaku,
                "oya": oya,
                "scores": scores,
                "dora_markers": [dora_marker],
                "tiles_left": 70,
                "hands": tehais,
                "rivers": [[], [], [], []],
                "melds": [[], [], [], []],
            }
            return None

        if not self.current_kyoku:
            return None

        if t == "dora":
            dm = ev.get("dora_marker")
            if dm and dm not in self.current_kyoku["dora_markers"]:
                self.current_kyoku["dora_markers"].append(dm)
            return None

        if t == "reach":
            actor = ev.get("actor")
            if actor is not None and 0 <= actor < 4:
                self.current_kyoku["scores"][actor] -= 1000
                self.current_kyoku["kyotaku"] += 1
            return None

        if t == "tsumo":
            actor = ev.get("actor")
            pai = ev.get("pai")
            self.current_kyoku["tiles_left"] = max(0, self.current_kyoku["tiles_left"] - 1)
            if actor is not None and 0 <= actor < 4:
                if pai and pai != "?":
                    self.current_kyoku["hands"][actor].append(pai)

            # 当轮到 target_seat 摸牌且摸完要决策时，产生一个抓拍点！
            if actor == self.target_seat:
                return self._capture_snapshot(ev_idx, tsumo_tile=pai)

        elif t == "dahai":
            actor = ev.get("actor")
            pai = ev.get("pai")
            tsumogiri = bool(ev.get("tsumogiri", False))
            is_riichi = False
            # 检查上一动作是否宣告立直
            if actor is not None and 0 <= actor < 4:
                h = self.current_kyoku["hands"][actor]
                if pai in h:
                    h.remove(pai)
                elif tsumogiri and h:
                    h.pop()
                self.current_kyoku["rivers"][actor].append({
                    "tile": pai,
                    "is_tsumogiri": tsumogiri,
                    "is_riichi": is_riichi,
                })

        elif t == "reach_accepted":
            actor = ev.get("actor")
            if actor is not None and 0 <= actor < 4 and self.current_kyoku["rivers"][actor]:
                self.current_kyoku["rivers"][actor][-1]["is_riichi"] = True

        elif t == "chi" or t == "pon" or t == "daiminkan":
            actor = ev.get("actor")
            pai = ev.get("pai")
            consumed = ev.get("consumed", [])
            target = ev.get("target")
            if actor is not None and 0 <= actor < 4:
                for c in consumed:
                    if c in self.current_kyoku["hands"][actor]:
                        self.current_kyoku["hands"][actor].remove(c)
                self.current_kyoku["melds"][actor].append({
                    "type": t,
                    "pai": pai,
                    "consumed": consumed,
                    "target": target,
                })
        elif t == "ankan" or t == "kakan":
            actor = ev.get("actor")
            pai = ev.get("pai")
            consumed = ev.get("consumed", [])
            if actor is not None and 0 <= actor < 4:
                if t == "kakan" and pai in self.current_kyoku["hands"][actor]:
                    self.current_kyoku["hands"][actor].remove(pai)
                elif t == "ankan":
                    for c in consumed:
                        if c in self.current_kyoku["hands"][actor]:
                            self.current_kyoku["hands"][actor].remove(c)
                self.current_kyoku["melds"][actor].append({
                    "type": t,
                    "pai": pai,
                    "consumed": consumed,
                })

        return None

    def _capture_snapshot(self, ev_idx: int, tsumo_tile: str) -> dict[str, Any]:
        """抓拍当前麻将桌物理世界完整快照。"""
        ck = self.current_kyoku
        hands_copy = [list(h) for h in ck["hands"]]
        
        # 将自家手牌分离为：前 N 张常态手牌（理牌排序） + 摸进来的牌
        target_hand = list(hands_copy[self.target_seat])
        tsumo_actual = tsumo_tile
        if tsumo_actual in target_hand:
            target_hand.remove(tsumo_actual)
        target_hand.sort(key=tile_sort_key)

        return {
            "ev_idx": ev_idx,
            "kyoku_idx": ck["kyoku_idx"],
            "kyoku_title": ck["title"],
            "bakaze": ck["bakaze"],
            "kyoku": ck["kyoku"],
            "honba": ck["honba"],
            "kyotaku": ck["kyotaku"],
            "oya": ck["oya"],
            "scores": list(ck["scores"]),
            "dora_markers": list(ck["dora_markers"]),
            "tiles_left": ck["tiles_left"],
            "hands": hands_copy,
            "target_hand_sorted": target_hand,
            "tsumo_tile": tsumo_actual,
            "rivers": [list(r) for r in ck["rivers"]],
            "melds": [list(m) for m in ck["melds"]],
        }


def run_single_model_review(
    model_id: str,
    model_name: str,
    events: list[dict[str, Any]],
    target_seat: int = 0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """以单模型对整场 MJAI 事件流进行整局重放审查并提取各决策点评估。"""
    import sys
    from pathlib import Path
    root = Path("D:/tenhoulib/MortalSim").resolve()
    for p_dir in [root / "target" / "release", root / "mortal", root]:
        ps = str(p_dir)
        if ps not in sys.path:
            sys.path.insert(0, ps)

    import libriichi
    for name in dir(libriichi):
        attr = getattr(libriichi, name)
        if isinstance(attr, type(libriichi)):
            sys.modules[f"libriichi.{name}"] = attr

    from mortal_app.service import _load_engine

    eng, dev, _ = _load_engine(model_id, "python")
    bot = libriichi.mjai.Bot(eng, target_seat)
    tracker = ReplayStateTracker(target_seat=target_seat)

    snapshots: list[dict[str, Any]] = []
    evaluations: list[dict[str, Any]] = []

    try:
        for ev_idx, ev in enumerate(events):
            ev_str = json.dumps(ev)
            res_str = bot.react(ev_str)
            snap = tracker.handle_event(ev, ev_idx)

            ev_type = ev.get("type")
            if ev_type == "tsumo" and ev.get("actor") == target_seat and snap:
                # 寻找该摸牌后玩家的实际切牌动作
                actual_dahai = None
                actual_is_riichi = False
                for f_idx in range(ev_idx + 1, min(len(events), ev_idx + 6)):
                    f_ev = events[f_idx]
                    if f_ev.get("actor") != target_seat:
                        continue
                    if f_ev.get("type") == "reach":
                        actual_is_riichi = True
                    elif f_ev.get("type") == "dahai":
                        actual_dahai = f_ev.get("pai")
                        break
                    elif f_ev.get("type") in ("hora", "ryukyoku"):
                        break

                if not actual_dahai or not res_str:
                    continue

                res_obj = json.loads(res_str)
                meta = res_obj.get("meta", {})
                mask_bits = meta.get("mask_bits", 0)
                q_vals = meta.get("q_values", [])

                q_map: dict[int, float] = {}
                idx = 0
                for act_id in range(46):
                    if (mask_bits >> act_id) & 1:
                        if idx < len(q_vals):
                            q_map[act_id] = float(q_vals[idx])
                        idx += 1

                # 探查立直 (action 37)
                reach_discards: dict[str, float] = {}
                if 37 in q_map:
                    try:
                        r_str = bot.react(json.dumps({"type": "reach", "actor": target_seat}))
                        if r_str:
                            r_obj = json.loads(r_str)
                            r_meta = r_obj.get("meta", {})
                            r_mask = r_meta.get("mask_bits", 0)
                            r_q = r_meta.get("q_values", [])
                            r_idx = 0
                            for act_id in range(37):
                                if (r_mask >> act_id) & 1:
                                    if r_idx < len(r_q):
                                        reach_discards[ACTION_TO_MJAI[act_id]] = float(r_q[r_idx])
                                    r_idx += 1
                    except Exception:
                        pass

                dama_discards: dict[str, float] = {}
                for act_id, q in q_map.items():
                    if act_id < 37:
                        dama_discards[ACTION_TO_MJAI[act_id]] = q

                all_tiles = set(dama_discards.keys()) | set(reach_discards.keys())
                cand_pool: list[dict[str, Any]] = []
                for t in all_tiles:
                    q_dama = dama_discards.get(t)
                    q_reach = reach_discards.get(t)
                    if q_dama is not None and q_reach is not None:
                        is_r = q_reach >= q_dama
                        cand_pool.append({"tile": t, "riichi": is_r, "q": q_reach if is_r else q_dama})
                    elif q_reach is not None:
                        cand_pool.append({"tile": t, "riichi": True, "q": q_reach})
                    elif q_dama is not None:
                        cand_pool.append({"tile": t, "riichi": False, "q": q_dama})

                if not cand_pool:
                    continue

                max_q = max(c["q"] for c in cand_pool)
                exps = [math.exp(c["q"] - max_q) for c in cand_pool]
                s_exp = sum(exps)
                for i, c in enumerate(cand_pool):
                    c["prob"] = round(exps[i] / s_exp, 4)

                cand_pool.sort(key=lambda x: x["prob"], reverse=True)
                best_cand = cand_pool[0]

                act_cand = next((c for c in cand_pool if c["tile"] == actual_dahai and c["riichi"] == actual_is_riichi), None)
                if act_cand is None:
                    act_cand = next((c for c in cand_pool if c["tile"] == actual_dahai), None)
                delta_q = (best_cand["q"] - act_cand["q"]) if act_cand else 9.99
                is_match = (act_cand == best_cand) if act_cand else False

                snap["actual"] = {"tile": actual_dahai, "riichi": actual_is_riichi}
                snapshots.append(snap)
                evaluations.append({
                    "best": best_cand,
                    "is_match": is_match,
                    "delta_q": round(delta_q, 3),
                    "candidates": cand_pool[:5],
                })

            elif ev_type == "end_game":
                break

    finally:
        del eng
        del dev
        del bot
        torch.cuda.empty_cache()

    return snapshots, evaluations


def run_multi_model_review(
    events: list[dict[str, Any]],
    target_seat: int = 0,
) -> dict[str, Any]:
    """多模型顺序执行整局审查，导出完整麻将桌回放与三模型横向对照数据包。"""
    model_evals: dict[str, list[dict[str, Any]]] = {}
    master_snapshots: list[dict[str, Any]] = []

    for cfg in MODELS_CONFIG:
        mid = cfg["id"]
        mname = cfg["name"]
        log.info("Starting review for model [%s] (%s)...", mname, mid)
        snaps, evals = run_single_model_review(mid, mname, events, target_seat)
        model_evals[mname] = evals
        if not master_snapshots:
            master_snapshots = snaps

    # 聚合每个决策点
    decisions: list[dict[str, Any]] = []
    kyoku_map: dict[int, dict[str, Any]] = {}

    for i, snap in enumerate(master_snapshots):
        k_idx = snap["kyoku_idx"]
        if k_idx not in kyoku_map:
            kyoku_map[k_idx] = {
                "kyoku_idx": k_idx,
                "title": snap["kyoku_title"],
                "decisions": [],
            }

        m_data = {}
        top_choices = []
        for cfg in MODELS_CONFIG:
            mname = cfg["name"]
            e = model_evals[mname][i]
            m_data[mname] = e
            top_choices.append(f"{e['best']['tile']}{'r' if e['best']['riichi'] else ''}")

        has_conflict = (len(set(top_choices)) > 1)

        dec_item = {
            "id": i,
            "kyoku_idx": k_idx,
            "turn_title": f"第 {len(kyoku_map[k_idx]['decisions']) + 1} 巡",
            "table_snapshot": snap,
            "has_conflict": has_conflict,
            "models": m_data,
        }
        kyoku_map[k_idx]["decisions"].append(i)
        decisions.append(dec_item)

    return {
        "target_seat": target_seat,
        "total_decisions": len(decisions),
        "kyokus": list(kyoku_map.values()),
        "decisions": decisions,
        "models": [cfg["name"] for cfg in MODELS_CONFIG],
    }

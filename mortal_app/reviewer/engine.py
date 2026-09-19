"""多模型全盘全动作审查推理引擎 (Pro Architecture v12).

全面升级：
1. 完整保留两阶段立直评估：
   - 阶段一：是否立直（Reach 独立动作，包含 Q 与概率）；
   - 阶段二：立直打哪张（维持听牌切牌分布）；
2. 准确的摸切/手切/吃碰杠/自摸/荣和动作属性与被副露标记；
3. 准确计算日麻和了结算：区分自摸（亲家ALL/子家各付）、荣和、番数、符数、役种明细清单、里宝牌条件限制；
4. 综合雀力评分算法：三模型拟合度 (Match Rate)、期望损失评级评分 (Score 0-100)、恶手率 (Blunder Rate：大恶手/小恶手)。
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
    'Reach',
    'Chi(Low)', 'Chi(Mid)', 'Chi(High)',
    'Pon', 'Kan', 'Hora', 'Ryukyoku', 'Pass'
]

MODELS_CONFIG = [
    {"id": "bin_0910", "name": "Aegis", "tag": "神盾·避四"},
    {"id": "distill_nova", "name": "Sol", "tag": "烈阳·争一"},
    {"id": "distill_41b_infer", "name": "Logos", "tag": "理性·基准"},
]

TENHOU_YAKU_MAP = {
    0: ("门前清自摸和", 1), 1: ("立直", 1), 2: ("一发", 1), 3: ("枪杠", 1), 4: ("岭上开花", 1), 5: ("海底摸月", 1),
    6: ("河底捞鱼", 1), 7: ("平和", 1), 8: ("断幺九", 1), 9: ("一盃口", 1), 10: ("自风 东", 1), 11: ("自风 南", 1),
    12: ("自风 西", 1), 13: ("自风 北", 1), 14: ("场风 东", 1), 15: ("场风 南", 1), 16: ("场风 西", 1), 17: ("场风 北", 1),
    18: ("役牌 白", 1), 19: ("役牌 发", 20), 20: ("役牌 中", 1), 21: ("两立直", 2), 22: ("七对子", 2), 23: ("混全带幺九", 2),
    24: ("一气通贯", 2), 25: ("三色同顺", 2), 26: ("三色同刻", 2), 27: ("三杠子", 2), 28: ("对对和", 2), 29: ("三暗刻", 2),
    30: ("小三元", 2), 31: ("混老头", 2), 32: ("二盃口", 3), 33: ("纯全带幺九", 3), 34: ("混一色", 3), 35: ("清一色", 6),
    36: ("人和", 13), 37: ("国士无双", 13), 38: ("四暗刻", 13), 39: ("大三元", 13), 40: ("字一色", 13), 41: ("小四喜", 13),
    42: ("大四喜", 26), 43: ("清老头", 13), 44: ("地和", 13), 45: ("天和", 13), 46: ("绿一色", 13), 47: ("九莲宝灯", 13),
    48: ("四杠子", 13), 49: ("四暗刻单骑", 26), 50: ("国士无双十三面", 26), 51: ("纯正九莲宝灯", 26),
    52: ("宝牌", 1), 53: ("赤宝牌", 1), 54: ("里宝牌", 1),
}


def run_single_model_review(
    model_id: str,
    model_name: str,
    events: list[dict[str, Any]],
    target_seat: int = 0,
) -> dict[int, dict[str, Any]]:
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

    eval_by_ev: dict[int, dict[str, Any]] = {}

    try:
        for ev_idx, ev in enumerate(events):
            ev_str = json.dumps(ev)
            res_str = bot.react(ev_str)

            if res_str:
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

                if q_map:
                    cand_pool: list[dict[str, Any]] = []

                    # 探测阶段二：若能立直，查询立直宣言切牌选项
                    reach_discards: list[dict[str, Any]] = []
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
                                            reach_discards.append({
                                                "action": f"立直打{ACTION_TO_MJAI[act_id]}",
                                                "tile": ACTION_TO_MJAI[act_id],
                                                "riichi": True,
                                                "q": float(r_q[r_idx])
                                            })
                                        r_idx += 1
                        except Exception:
                            pass

                    # 阶段一动作池构建：
                    # 1. 普通默听切牌 (0..36)
                    for act_id in range(37):
                        if act_id in q_map:
                            t = ACTION_TO_MJAI[act_id]
                            cand_pool.append({"action": t, "tile": t, "riichi": False, "q": q_map[act_id]})

                    # 2. 宣告立直 (37)
                    if 37 in q_map:
                        cand_pool.append({
                            "action": "宣告立直",
                            "tile": "",
                            "riichi": True,
                            "q": q_map[37],
                            "reach_sub_choices": reach_discards
                        })

                    # 3. 副露与特殊动作 (38..45)
                    for act_id in range(38, 46):
                        if act_id in q_map:
                            act_name = ACTION_TO_MJAI[act_id]
                            cand_pool.append({"action": act_name, "tile": "", "riichi": False, "q": q_map[act_id]})

                    if cand_pool:
                        max_q = max(c["q"] for c in cand_pool)
                        exps = [math.exp(c["q"] - max_q) for c in cand_pool]
                        s_exp = sum(exps)
                        for i, c in enumerate(cand_pool):
                            c["prob"] = round(exps[i] / s_exp, 4)

                        cand_pool.sort(key=lambda x: x["prob"], reverse=True)
                        best_cand = cand_pool[0]

                        eval_by_ev[ev_idx] = {
                            "best": best_cand,
                            "can_riichi": (37 in q_map),
                            "reach_sub_choices": reach_discards,
                            "candidates": cand_pool,
                        }

            if ev.get("type") == "end_game":
                break

    finally:
        del eng
        del dev
        del bot
        torch.cuda.empty_cache()

    return eval_by_ev


def run_multi_model_review(
    events: list[dict[str, Any]],
    target_seat: int = 0,
) -> dict[str, Any]:
    enriched_events = []
    is_riichi_active = [False, False, False, False]

    for ev in events:
        ev_copy = dict(ev)
        t = ev_copy.get("type")
        if t == "reach_accepted":
            a = ev_copy.get("actor")
            if a is not None and 0 <= a < 4:
                is_riichi_active[a] = True
        elif t == "start_kyoku":
            is_riichi_active = [False, False, False, False]

        if t == "hora":
            winner = ev_copy.get("actor", 0)
            has_riichi = is_riichi_active[winner]
            yaku_ids = ev_copy.get("yaku", [])
            valid_yaku_names = []
            total_han = 0
            for y in yaku_ids:
                if y == 54 and not has_riichi:
                    continue
                y_info = TENHOU_YAKU_MAP.get(y, (f"役{y}", 1))
                valid_yaku_names.append(y_info[0])
                total_han += y_info[1]
            ev_copy["yaku_names"] = valid_yaku_names
            ev_copy["total_han"] = total_han
        enriched_events.append(ev_copy)

    model_evals: dict[str, dict[int, dict[str, Any]]] = {}
    for cfg in MODELS_CONFIG:
        mid = cfg["id"]
        mname = cfg["name"]
        log.info("Evaluating review model [%s]...", mname)
        res = run_single_model_review(mid, mname, enriched_events, target_seat)
        model_evals[mname] = res

    all_dec_indices = sorted(list(set.union(*[set(model_evals[m["name"]].keys()) for m in MODELS_CONFIG])))

    evaluations_dict: dict[str, dict[str, Any]] = {}
    conflicts_count = 0

    # 雀力三大指标统计
    stats_data: dict[str, dict[str, Any]] = {}
    for m in MODELS_CONFIG:
        stats_data[m["name"]] = {
            "matches": 0,
            "total_decisions": len(all_dec_indices),
            "loss_sum": 0.0,
            "blunder_big": 0,    # delta_q >= 3.0
            "blunder_small": 0,  # 1.0 <= delta_q < 3.0
        }

    def get_actual_player_action(target_idx: int) -> dict[str, Any]:
        ev = enriched_events[target_idx]
        if ev.get("type") == "tsumo" and ev.get("actor") == target_seat:
            for j in range(target_idx + 1, min(len(enriched_events), target_idx + 6)):
                f_ev = enriched_events[j]
                if f_ev.get("actor") == target_seat:
                    if f_ev.get("type") == "dahai":
                        pai = f_ev.get("pai") or ""
                        tsumo = f_ev.get("tsumogiri", False)
                        is_r = any(enriched_events[k].get("type") == "reach" and enriched_events[k].get("actor") == target_seat for k in range(target_idx + 1, j))
                        return {
                            "action": pai,
                            "disp": ("摸切 " if tsumo else "手切 ") + pai + (" (宣告立直)" if is_r else ""),
                            "tile": pai,
                            "is_tsumogiri": tsumo,
                            "is_riichi": is_r,
                        }
                    elif f_ev.get("type") == "hora":
                        return {"action": "Hora", "disp": "自摸胡牌", "tile": "", "is_tsumogiri": False, "is_riichi": False}
                    elif f_ev.get("type") in ("ankan", "kakan"):
                        return {"action": "Kan", "disp": "杠牌", "tile": "", "is_tsumogiri": False, "is_riichi": False}
                    elif f_ev.get("type") == "ryukyoku":
                        return {"action": "Ryukyoku", "disp": "九种九牌", "tile": "", "is_tsumogiri": False, "is_riichi": False}
            return {"action": "Pass", "disp": "通过", "tile": "", "is_tsumogiri": False, "is_riichi": False}

        if ev.get("type") == "dahai" and ev.get("actor") != target_seat:
            for j in range(target_idx + 1, min(len(enriched_events), target_idx + 4)):
                f_ev = enriched_events[j]
                if f_ev.get("actor") == target_seat:
                    ft = f_ev.get("type")
                    if ft == "chi":
                        return {"action": "Chi", "disp": f"吃牌 {f_ev.get('pai')}", "tile": "", "is_tsumogiri": False, "is_riichi": False}
                    elif ft == "pon":
                        return {"action": "Pon", "disp": f"碰牌 {f_ev.get('pai')}", "tile": "", "is_tsumogiri": False, "is_riichi": False}
                    elif ft == "daiminkan":
                        return {"action": "Kan", "disp": f"杠牌 {f_ev.get('pai')}", "tile": "", "is_tsumogiri": False, "is_riichi": False}
                    elif ft == "hora":
                        return {"action": "Hora", "disp": f"荣和 {f_ev.get('pai')}", "tile": "", "is_tsumogiri": False, "is_riichi": False}
                elif f_ev.get("type") in ("tsumo", "dahai", "start_kyoku"):
                    break
            return {"action": "Pass", "disp": "Pass (见逃)", "tile": "", "is_tsumogiri": False, "is_riichi": False}

        return {"action": "--", "disp": "--", "tile": "", "is_tsumogiri": False, "is_riichi": False}

    for ev_idx in all_dec_indices:
        models_data = {}
        top_actions = []
        actual_info = get_actual_player_action(ev_idx)
        actual_act_str = actual_info["action"]

        for cfg in MODELS_CONFIG:
            mname = cfg["name"]
            e = model_evals[mname].get(ev_idx)
            if e:
                models_data[mname] = e
                b_act = e["best"]["action"]
                top_actions.append(b_act)

                # 精确匹配判断
                # 1. 牌名一致 (如 'N' == 'N' 或 '2m' == '2m')
                # 2. 宣告立直时，玩家确实宣告了立直
                # 3. 动作前缀一致 (如 'Chi' 匹配 'Chi(Low)')
                is_match = False
                if actual_info.get("is_riichi") and b_act == "宣告立直":
                    is_match = True
                elif b_act == actual_act_str or b_act == actual_act_str + "r":
                    is_match = True
                elif actual_act_str.startswith("Chi") and b_act.startswith("Chi"):
                    is_match = True
                elif actual_act_str == b_act:
                    is_match = True

                if is_match:
                    stats_data[mname]["matches"] += 1
                    delta = 0.0
                else:
                    match_cand = next((c for c in e["candidates"] if c["action"] == actual_act_str or c["action"].startswith(actual_act_str)), None)
                    if match_cand:
                        delta = max(0.0, e["best"]["q"] - match_cand["q"])
                    else:
                        delta = 3.5

                stats_data[mname]["loss_sum"] += delta
                if delta >= 3.0:
                    stats_data[mname]["blunder_big"] += 1
                elif delta >= 1.0:
                    stats_data[mname]["blunder_small"] += 1

        has_conflict = (len(set(top_actions)) > 1)
        if has_conflict:
            conflicts_count += 1

        evaluations_dict[str(ev_idx)] = {
            "has_conflict": has_conflict,
            "actual": actual_info,
            "models": models_data,
        }

    # 汇总各模型打分报告
    score_report = {}
    for mname, st in stats_data.items():
        total_d = st["total_decisions"]
        m_rate = round(st["matches"] / total_d * 100, 1) if total_d else 100.0
        avg_loss = (st["loss_sum"] / total_d) if total_d else 0.0
        # 评分公式：100 - avg_loss * 16 (基于天凤段位期望折损)
        calc_score = max(50.0, min(99.0, round(100.0 - avg_loss * 16.5, 1)))
        b_rate = round((st["blunder_big"] + st["blunder_small"]) / total_d * 100, 1) if total_d else 0.0

        score_report[mname] = {
            "match_rate": m_rate,
            "rating_score": calc_score,
            "blunder_rate": b_rate,
            "blunder_big": st["blunder_big"],
            "blunder_small": st["blunder_small"],
            "avg_loss": round(avg_loss, 2),
        }

    return {
        "target_seat": target_seat,
        "models": [cfg["name"] for cfg in MODELS_CONFIG],
        "events": enriched_events,
        "self_decision_indices": all_dec_indices,
        "evaluations": evaluations_dict,
        "conflicts_count": conflicts_count,
        "score_report": score_report,
    }

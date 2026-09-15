"""多模型审查推理核心引擎 (Multi-Model Review Engine).

功能与架构保证：
1. 顺序审查（Aegis -> Sol -> Logos），推断完即刻释放显存，严守 6GB 显存预算；
2. 动作空间对齐：基于 libriichi 全局 Tile ID 提取合法切牌，字牌统一 E,S,W,N,P,F,C，赤牌 5mr,5pr,5sr；
3. 两阶段立直处理：正确分离 Reach 宣告与 Reach Dahai 决策；
4. 概率 P 与价值 Q 正规化分离，计算单模型恶手值与三模型战术分歧。
"""
from __future__ import annotations

import json
import logging
import math
from typing import Any
import torch

log = logging.getLogger("reviewer.engine")

# libriichi 标准 37 切牌动作与 MJAI 牌名双向真源
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

def run_single_model_review(
    model_id: str,
    model_name: str,
    events: list[dict[str, Any]],
    target_seat: int = 0,
) -> list[dict[str, Any]]:
    """以单模型对整场 MJAI 事件流进行整局重放审查。"""
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

    decisions: list[dict[str, Any]] = []

    try:
        for ev_idx, ev in enumerate(events):
            ev_str = json.dumps(ev)
            res_str = bot.react(ev_str)
            ev_type = ev.get("type")

            # 当轮到 target_seat 摸牌并进行切牌决策时
            if ev_type == "tsumo" and ev.get("actor") == target_seat:
                # 寻找该摸牌事件后紧随的玩家实际切牌动作 (dahai)
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
                    except Exception as rexc:
                        log.debug("探查立直动作失败（跳过立直打牌分支）: %s", rexc)

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

                # Softmax 概率正规化
                max_q = max(c["q"] for c in cand_pool)
                exps = [math.exp(c["q"] - max_q) for c in cand_pool]
                s_exp = sum(exps)
                for i, c in enumerate(cand_pool):
                    c["prob"] = round(exps[i] / s_exp, 4)

                cand_pool.sort(key=lambda x: x["prob"], reverse=True)
                best_cand = cand_pool[0]

                # 计算实际切牌在该模型视角下的 Q 损失 (恶手度 delta_q)
                act_cand = next((c for c in cand_pool if c["tile"] == actual_dahai and c["riichi"] == actual_is_riichi), None)
                if act_cand is None:
                    act_cand = next((c for c in cand_pool if c["tile"] == actual_dahai), None)
                delta_q = (best_cand["q"] - act_cand["q"]) if act_cand else 9.99

                is_match = (act_cand == best_cand) if act_cand else False

                decisions.append({
                    "event_idx": ev_idx,
                    "actual": {"tile": actual_dahai, "riichi": actual_is_riichi},
                    "model_eval": {
                        "best": best_cand,
                        "is_match": is_match,
                        "delta_q": round(delta_q, 3),
                        "candidates": cand_pool[:5], # 保留前 5 项供 UI 对照
                    }
                })

            elif ev_type == "end_game":
                break

    finally:
        # 强制释放显存
        del eng
        del dev
        del bot
        torch.cuda.empty_cache()

    return decisions


def run_multi_model_review(
    events: list[dict[str, Any]],
    target_seat: int = 0,
) -> dict[str, Any]:
    """多模型顺序执行整局审查，汇总分歧矩阵与三模型决策流。"""
    model_results: dict[str, list[dict[str, Any]]] = {}

    for cfg in MODELS_CONFIG:
        mid = cfg["id"]
        mname = cfg["name"]
        log.info("Starting review for model [%s] (%s)...", mname, mid)
        res = run_single_model_review(mid, mname, events, target_seat)
        model_results[mname] = res

    # 聚合到决策点统一时间线
    timeline: list[dict[str, Any]] = []
    first_model_decisions = model_results[MODELS_CONFIG[0]["name"]]

    for i, base_dec in enumerate(first_model_decisions):
        ev_idx = base_dec["event_idx"]
        actual = base_dec["actual"]

        models_data = {}
        top_choices = []
        for cfg in MODELS_CONFIG:
            mname = cfg["name"]
            m_eval = model_results[mname][i]["model_eval"]
            models_data[mname] = m_eval
            best = m_eval["best"]
            top_choices.append(f"{best['tile']}{'r' if best['riichi'] else ''}")

        # 判定是否存在战术分歧 (三模型最优解不完全一致)
        has_conflict = (len(set(top_choices)) > 1)

        timeline.append({
            "event_idx": ev_idx,
            "actual": actual,
            "has_conflict": has_conflict,
            "models": models_data,
        })

    return {
        "target_seat": target_seat,
        "total_decisions": len(timeline),
        "timeline": timeline,
        "models": [cfg["name"] for cfg in MODELS_CONFIG],
    }

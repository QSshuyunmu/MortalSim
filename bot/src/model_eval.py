"""model_eval.py — 调用 Mortal 模型对当前局面进行瞬时前向推断，输出 Q 值最高的合法切牌候选。"""
from __future__ import annotations

import json
import logging
import math
from typing import Any
from pathlib import Path
import sys

# 动态确保 mortal 与 libriichi 模块可用
MORTALSIM_ROOT = Path("D:/tenhoulib/MortalSim").resolve()
for p in [MORTALSIM_ROOT / "target" / "release", MORTALSIM_ROOT / "mortal", MORTALSIM_ROOT]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

import libriichi
from mortal_app.service import _load_engine
from simulator.kyoku_sim_win import parse_hand

log = logging.getLogger("model_eval")

ACTION_TO_TILE = [
    '1m','2m','3m','4m','5m','6m','7m','8m','9m',
    '1p','2p','3p','4p','5p','6p','7p','8p','9p',
    '1s','2s','3s','4s','5s','6s','7s','8s','9s',
    '1z','2z','3z','4z','5z','6z','7z',
    '0m','0p','0s',
]

TO_MJAI_HONOR = {
    '1z': 'E', '2z': 'S', '3z': 'W', '4z': 'N',
    '5z': 'P', '6z': 'F', '7z': 'C',
}

# 单例全局缓存已加载的 engine 实例，避免重复创建
_CACHED_ENGINES: dict[str, Any] = {}

def get_cached_engine(model_id: str = "distill_41b_infer") -> Any:
    if model_id not in _CACHED_ENGINES:
        eng, _, _ = _load_engine(model_id, "python")
        _CACHED_ENGINES[model_id] = eng
    return _CACHED_ENGINES[model_id]


def select_candidate_count(weights: list[float], min_x: int = 2, max_x: int = 4) -> int:
    """根据前 x 选的权重分布，动态选择候选数 x。

    用户规则：
    - 前 x 选模型给出的权重没有压倒性区别就输入这 x 选，x 最小为 2，最大为 max_x (默认 4)。
    - 典型基准：
      - [60, 38, 2] -> 前 2 选
      - [50, 30, 15, 5] -> 前 3 选
      - [30, 25, 20, 15, 10] -> 前 4 选
    """
    weights = sorted(weights, reverse=True)
    n = len(weights)
    if n <= min_x:
        return n

    x = min_x
    while x < min(n, max_x):
        w_curr = weights[x - 1]
        w_next = weights[x]
        cum = sum(weights[:x])

        # 判定第 x 选到第 x+1 选是否存在压倒性断崖：
        # 1. 累积覆盖率达到 88% 且 第 x+1 选权重极小 (< 0.08)
        # 2. 下一个权重相对当前跌幅超半 (< 0.45 * w_curr 且 < 0.12)
        # 3. 绝对差值达到 15% 且 下一个 < 0.10
        is_covered = (cum >= 0.88 and w_next < 0.08)
        is_cliff = (w_next < w_curr * 0.45 and w_next < 0.12) or (w_curr - w_next >= 0.15 and w_next < 0.10)

        if is_covered or is_cliff:
            break

        x += 1
    return x


def get_top_model_discards(
    hand_str: str,
    dora_indicator: str,
    round_str: str = "E1",
    target_seat: int = 0,
    scores: dict[str, int] | list[int] | None = None,
    model_id: str = "distill_41b_infer",
    min_k: int = 2,
    max_k: int = 4,
) -> list[tuple[str, bool]]:
    """使用 Mortal 模型前向推断当前手牌所有合法切牌（包含立直打牌）的 Q 值与 Softmax 权重。

    返回:
        list of (tile, is_riichi)，例如 [('1s', True), ('7z', True)]。
        当权重无压倒性差异时动态扩展 x 选（x 最小为 min_k=2，最大为 max_k=4）。
    """
    try:
        engine = get_cached_engine(model_id)
        tiles = parse_hand(hand_str)
        if len(tiles) not in (13, 14):
            return []

        # 4家分数构造
        if isinstance(scores, dict):
            s_self = scores.get("self", 25000)
            s_shimo = scores.get("shimocha", 25000)
            s_toi = scores.get("toimen", 25000)
            s_kami = 100000 - s_self - s_shimo - s_toi
            score_list = [25000, 25000, 25000, 25000]
            score_list[target_seat] = s_self
            score_list[(target_seat + 1) % 4] = s_shimo
            score_list[(target_seat + 2) % 4] = s_toi
            score_list[(target_seat + 3) % 4] = s_kami
        elif isinstance(scores, list) and len(scores) == 4:
            score_list = [int(s) for s in scores]
        else:
            score_list = [25000, 25000, 25000, 25000]

        bot = libriichi.mjai.Bot(engine, target_seat)
        bot.react(json.dumps({"type": "start_game"}))

        bakaze = round_str[0].upper() if round_str else "E"
        kyoku_num = int(round_str[1]) if len(round_str) > 1 and round_str[1].isdigit() else 1
        oya = 0

        # mjai 协议要求字牌 1z..7z 表示为 E, S, W, N, P, F, C
        mjai_dora = TO_MJAI_HONOR.get(dora_indicator, dora_indicator)
        mjai_tiles = [TO_MJAI_HONOR.get(t, t) for t in tiles]

        # 宝牌指示牌若与手牌重合导致全局该牌超过 4 张，安全替换为不冲突的指示牌（仅用于前向推断候选切牌）
        eval_dora = mjai_dora
        if mjai_tiles.count(eval_dora) == 4:
            for cand_dora in ["C", "F", "P", "N", "W", "S", "E", "1s", "9s", "1p", "9p"]:
                if cand_dora not in mjai_tiles:
                    eval_dora = cand_dora
                    break

        tehais = [["?"] * 13 for _ in range(4)]
        if len(mjai_tiles) == 14:
            tsumo_idx = -1
            for i in range(len(mjai_tiles) - 1, -1, -1):
                t = mjai_tiles[i]
                sub = mjai_tiles[:i] + mjai_tiles[i+1:]
                dora_count = 1 if t == eval_dora else 0
                if sub.count(t) + dora_count < 4:
                    tsumo_idx = i
                    break
            if tsumo_idx == -1:
                tsumo_idx = len(mjai_tiles) - 1
            tsumo_tile = mjai_tiles[tsumo_idx]
            tehais[target_seat] = mjai_tiles[:tsumo_idx] + mjai_tiles[tsumo_idx+1:]
        else:
            tehais[target_seat] = mjai_tiles
            tsumo_tile = mjai_tiles[-1]

        bot.react(json.dumps({
            "type": "start_kyoku",
            "bakaze": bakaze,
            "kyoku": kyoku_num,
            "honba": 0,
            "kyotaku": 0,
            "oya": oya,
            "dora_marker": eval_dora,
            "scores": score_list,
            "tehais": tehais,
        }))

        res_str = bot.react(json.dumps({
            "type": "tsumo",
            "actor": target_seat,
            "pai": tsumo_tile,
        }))
        if not res_str:
            return []

        res = json.loads(res_str)
        meta = res.get("meta", {})
        q_vals = meta.get("q_values", [])
        mask_bits = meta.get("mask_bits", 0)

        q_map: dict[int, float] = {}
        idx = 0
        for action_id in range(46):
            if (mask_bits >> action_id) & 1:
                if idx < len(q_vals):
                    q_map[action_id] = float(q_vals[idx])
                idx += 1

        # 检查是否可以立直 (action_id == 37)
        # 若能立直，向 bot 声明 reach 并提取各立直打牌动作及具体 Q 值
        reach_discards: dict[str, float] = {}
        if 37 in q_map:
            try:
                reach_res_str = bot.react(json.dumps({"type": "reach", "actor": target_seat}))
                if reach_res_str:
                    reach_res = json.loads(reach_res_str)
                    reach_meta = reach_res.get("meta", {})
                    reach_mask = reach_meta.get("mask_bits", 0)
                    reach_q_vals = reach_meta.get("q_values", [])
                    reach_idx = 0
                    for r_act in range(37):
                        if (reach_mask >> r_act) & 1:
                            if reach_idx < len(reach_q_vals):
                                reach_discards[ACTION_TO_TILE[r_act]] = float(reach_q_vals[reach_idx])
                            reach_idx += 1
            except Exception as reach_err:
                log.warning("探查立直切牌失败: %s", reach_err)

        dama_discards: dict[str, float] = {}
        for act_id, q in q_map.items():
            if act_id < 37:
                dama_discards[ACTION_TO_TILE[act_id]] = q

        # 将每个可切牌的"立直"与"默听"按最高 Q 值决策合并
        all_candidate_tiles = set(dama_discards.keys()) | set(reach_discards.keys())
        candidates_pool: list[tuple[str, bool, float]] = []
        for t in all_candidate_tiles:
            q_dama = dama_discards.get(t)
            q_reach = reach_discards.get(t)
            if q_dama is not None and q_reach is not None:
                if q_reach >= q_dama:
                    candidates_pool.append((t, True, q_reach))
                else:
                    candidates_pool.append((t, False, q_dama))
            elif q_reach is not None:
                candidates_pool.append((t, True, q_reach))
            elif q_dama is not None:
                candidates_pool.append((t, False, q_dama))

        if not candidates_pool:
            return []

        # 计算 Softmax 权重分布
        max_q = max(c[2] for c in candidates_pool)
        exps = [math.exp(c[2] - max_q) for c in candidates_pool]
        sum_exp = sum(exps)
        probs = [e / sum_exp for e in exps]

        sorted_pool = sorted(zip(candidates_pool, probs), key=lambda x: x[1], reverse=True)
        weights = [p for _, p in sorted_pool]

        # 动态判定无压倒性差异的前 x 选
        k = select_candidate_count(weights, min_x=min_k, max_x=max_k)
        selected_candidates = [(c[0], c[1]) for c, _ in sorted_pool[:k]]

        log_details = [f"{c[0]}{'r' if c[1] else ''}({p*100:.1f}%)" for c, p in sorted_pool[:k]]
        log.info("模型前向推断完成，动态自适应选取前 %d 选: %s", k, ", ".join(log_details))

        return selected_candidates
    except Exception as exc:
        log.warning("模型前向推断候选失败，将降级处理: %s", exc)
        return []

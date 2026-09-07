"""model_eval.py — 调用 Mortal 模型对当前局面进行瞬时前向推断，输出 Q 值最高的合法切牌候选。"""
from __future__ import annotations

import json
import logging
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

# 单例全局缓存已加载的 engine 实例，避免重复创建
_CACHED_ENGINES: dict[str, Any] = {}

def get_cached_engine(model_id: str = "distill_41b_infer") -> Any:
    if model_id not in _CACHED_ENGINES:
        eng, _, _ = _load_engine(model_id, "python")
        _CACHED_ENGINES[model_id] = eng
    return _CACHED_ENGINES[model_id]

def get_top_model_discards(
    hand_str: str,
    dora_indicator: str,
    round_str: str = "E1",
    target_seat: int = 0,
    scores: dict[str, int] | list[int] | None = None,
    model_id: str = "distill_41b_infer",
    k: int = 3,
) -> list[str]:
    """使用 Mortal 模型前向推断当前手牌所有合法切牌的 Q 值，返回权重最高的前 k 个切牌候选（如 ['2p', '5m', '1p']）。"""
    try:
        engine = get_cached_engine(model_id)
        tiles = parse_hand(hand_str)
        if len(tiles) not in (13, 14):
            return []

        # 4家分数构造
        if isinstance(scores, dict):
            # {'self': 25000, 'shimocha': 25000, 'toimen': 25000}
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

        # 宝牌指示牌若与手牌重合导致全局该牌超过 4 张，安全替换为不冲突的指示牌（仅用于前向推断候选切牌）
        # 注意 mjai 协议字牌用 E, S, W, N, P, F, C
        eval_dora = dora_indicator
        if tiles.count(eval_dora) == 4:
            for cand_dora in ["C", "F", "P", "N", "W", "S", "E", "1s", "9s", "1p", "9p"]:
                if cand_dora not in tiles:
                    eval_dora = cand_dora
                    break

        tehais = [["?"] * 13 for _ in range(4)]
        if len(tiles) == 14:
            # 摸牌优先挑选使得初始 13 张 + eval_dora + tsumo 不超过 4 张的合法分配
            tsumo_idx = -1
            for i in range(len(tiles) - 1, -1, -1):
                t = tiles[i]
                sub = tiles[:i] + tiles[i+1:]
                dora_count = 1 if t == eval_dora else 0
                if sub.count(t) + dora_count < 4:
                    tsumo_idx = i
                    break
            if tsumo_idx == -1:
                tsumo_idx = len(tiles) - 1
            tsumo_tile = tiles[tsumo_idx]
            tehais[target_seat] = tiles[:tsumo_idx] + tiles[tsumo_idx+1:]
        else:
            tehais[target_seat] = tiles
            tsumo_tile = tiles[-1]

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

        legal_discards: list[tuple[str, float]] = []
        idx = 0
        for action_id in range(46):
            if (mask_bits >> action_id) & 1:
                if idx < len(q_vals):
                    q = q_vals[idx]
                    idx += 1
                    # 仅保留切牌动作 (action_id < 37)
                    if action_id < 37:
                        t = ACTION_TO_TILE[action_id]
                        # 转换赤牌别名：0m/0p/0s 还原为对应牌
                        legal_discards.append((t, float(q)))
                else:
                    idx += 1

        # 按 Q 值降序排序
        legal_discards.sort(key=lambda item: item[1], reverse=True)
        top_tiles = [item[0] for item in legal_discards[:k]]
        log.info("模型前向推断完成，Top %d 候选切牌: %s", k, legal_discards[:k])
        return top_tiles
    except Exception as exc:
        log.warning("模型前向推断候选失败，将降级处理: %s", exc)
        return []

"""model_eval.py — 调用 Mortal 模型对当前局面进行瞬时前向推断。

统一推断入口 (本模块的核心约定)::

    from model_eval import model_forward

    fwd = model_forward(hand_str=..., dora_indicator=..., ...)
    fwd["qp"]   # {candidate_key: {"q":..., "p":..., "riichi":...}}
    fwd["top"]  # [(tile, is_riichi, weight), ...] 动态自适应选取的前 x 选

设计要点：
    1. **一次前向推断同时产出"候选切牌"与"Q/P"** —— 这两件事本质是同一次
       engine 推断的两个视图（一个回答"打哪几张"，一个回答"Q值/归一概率"）。
       历史上 get_top_model_discards() 与 eval_model_qp() 各自跑一遍完整推断，
       在没有显式 c= 候选时等于把同一局面的推断流程重复执行；
       现在两者都是 model_forward() 的薄封装，且 bot 侧在无 c= 时把 qp 结果
       沿请求带下去复用（见 parser.py / bot.py 的 request["_model_qp"]）。
    2. 两个视图各自保留原有归一化口径：
       - Q/P: 两级分解（默听池 vs 宣告立直 → 立直后切牌池），不互相稀释。
       - top: 每张牌取"立直/默听"中 Q 更高者，合并后单池 softmax + 断崖判定。
"""
from __future__ import annotations

import json
import logging
import math
import os
from typing import Any
from pathlib import Path
import sys

# 动态确保 mortal 与 libriichi 模块可用
# 默认路径由本文件位置推导 (bot/src/model_eval.py -> 仓库根)，不再硬编码 D:/tenhoulib/...
# —— 硬编码路径在换机/换盘后会让推断整体静默降级 (except 吞掉异常 -> 候选走兜底)。
# 仓库根与 native 产物不在同一处时，用 MORTALSIM_ROOT 覆盖，不改本文件。
MORTALSIM_ROOT = Path(os.environ.get("MORTALSIM_ROOT") or Path(__file__).resolve().parents[2]).resolve()
for p in [MORTALSIM_ROOT / "target" / "release", MORTALSIM_ROOT / "mortal", MORTALSIM_ROOT]:
    p_str = str(p)
    if p_str not in sys.path:
        sys.path.insert(0, p_str)

# Native inference dependencies are loaded inside the guarded inference path.
# Importing model aliases or rendering a report must not require a local .pyd/GPU.

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

# 模型入口保持上游语义：仅 model_balanced / model_aggressive 两个别名会切换后端模型，
# 其余值一律落到默认模型。映射规则留在 parser.py / bot.py 的既有分支里，本模块不引入
# 新的解析层，避免把"换模型"这件事从既有入口挪到别处。
DEFAULT_MODEL_ID = "distill_41b_infer"

# 单例全局缓存已加载的 engine 实例，避免重复创建
_CACHED_ENGINES: dict[str, Any] = {}

def get_cached_engine(model_id: str = DEFAULT_MODEL_ID) -> Any:
    if model_id not in _CACHED_ENGINES:
        from mortal_app.service import _load_engine

        eng, _, _ = _load_engine(model_id, "python")
        _CACHED_ENGINES[model_id] = eng
    return _CACHED_ENGINES[model_id]


def _conditional_discard_view(
    response: dict[str, Any],
    candidate: dict[str, Any],
    tau: float = 0.1,
) -> dict[str, Any]:
    """P(discard | this exact call), over ALL legal post-call discards.

    This softmax is a display normalization, not the rollout sampling policy.
    An explicit >tile selects that tile's probability, never the argmax's.
    """
    from mortal_app.call_context import tile
    if response.get("type") != "dahai":
        raise ValueError("副露后模型未返回切牌决策")
    meta = response.get("meta") or {}
    mask_bits = int(meta.get("mask_bits", 0))
    ids = [i for i in range(46) if (mask_bits >> i) & 1]
    qs = meta.get("q_values") or []
    if not ids or len(ids) != len(qs) or any(i >= 37 for i in ids) or any(not math.isfinite(q) for q in qs):
        raise ValueError("副露后切牌Q/mask不完整")
    max_q = max(qs)
    tau_safe = max(1e-4, float(tau))
    weights = [math.exp((q - max_q) / tau_safe) for q in qs]
    total = sum(weights)
    distribution = {ACTION_TO_TILE[i]: {"q": float(q), "p": w / total} for i, q, w in zip(ids, qs, weights)}
    best_index = max(range(len(qs)), key=qs.__getitem__)
    best_tile = ACTION_TO_TILE[ids[best_index]]
    response_tile = tile(response.get("pai", best_tile))
    forced = candidate.get("follow_up_discard")
    selected = tile(forced) if forced else best_tile
    if selected not in distribution:
        raise ValueError(f"指定后切{selected}不在合法mask中")
    return {"tile": selected, "mode": "forced" if forced else "model", **distribution[selected],
            "model_tile": best_tile, "response_tile": response_tile, "distribution": distribution}


def _meld_followup_qp(engine: Any, target_seat: int, hand: list[str], call_tile: str,
                      prefix: list[dict[str, Any]], candidates: list[dict[str, Any]],
                      root_qp: dict[str, Any], tau: float = 0.1) -> dict[str, Any]:
    """Force each distinct call on a fresh bot; never share mutated branch state."""
    import libriichi
    from mortal_app.call_context import base, mjai, tile
    output = {key: dict(value) for key, value in root_qp.items()}
    # Pon can claim any opponent's latest discard, not only kamicha's. Replay
    # the same actor used by the validated response prefix for every branch.
    source_actor = next(event["actor"] for event in reversed(prefix) if event["type"] == "dahai")
    cache: dict[tuple, dict[str, Any]] = {}
    for candidate in candidates:
        chi = candidate.get("chi")
        pon = candidate.get("pon")
        if not (chi or pon):
            continue  # Pass/kan/ron are not post-call discard decisions.
        if chi:
            consumed = list(chi)
            root_id = f"chi:{''.join(consumed)}"
        else:
            consumed = sorted((tile(t) for t in hand if base(t) == base(call_tile)), key=lambda t: not t.startswith("0"))[:2]
            root_id = f"pon:{call_tile}"
        # The 46-action chi head names the sequence, not red tile consumption.
        parent = root_qp.get(root_id) or root_qp.get(f"chi:{''.join(base(t) for t in consumed)}" if chi else "pon")
        if parent is None:
            continue
        forced = candidate.get("follow_up_discard")
        cand_id = candidate.get("candidate") or root_id + (f">{forced}" if forced else "")
        out = dict(parent)
        try:
            key = ("chi" if chi else "pon", tuple(consumed), call_tile)
            if key not in cache:
                branch = libriichi.mjai.Bot(engine, target_seat)
                branch.react(json.dumps({"type": "start_game"}))
                for event in prefix:
                    branch.react(json.dumps(event))
                action = {"type": key[0], "actor": target_seat, "target": source_actor,
                          "pai": mjai(call_tile), "consumed": list(map(mjai, consumed))}
                answer = branch.react(json.dumps(action))
                if not answer:
                    raise ValueError("副露后没有模型响应")
                cache[key] = json.loads(answer)
            out["follow_up"] = _conditional_discard_view(cache[key], candidate, tau=tau)
        except Exception as exc:
            log.warning("%s 后切Q/P缺失: %s", cand_id, exc)
            out["follow_up"] = {"tile": forced, "mode": "forced" if forced else "model", "error": str(exc)}
        output[cand_id] = out
    return output


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


def _build_scores(
    scores: dict[str, int] | list[int] | None,
    target_seat: int,
    kyotaku: int = 0,
) -> list[int]:
    """把 dict/list 分数统一成 4 家数组，推导上家时扣除供托。"""
    if scores is None:
        scores = {}
    if isinstance(scores, dict):
        s_self = scores.get("self", 25000)
        s_shimo = scores.get("shimocha", 25000)
        s_toi = scores.get("toimen", 25000)
        s_kami = 100000 - kyotaku * 1000 - s_self - s_shimo - s_toi
        score_list = [25000, 25000, 25000, 25000]
        score_list[target_seat] = s_self
        score_list[(target_seat + 1) % 4] = s_shimo
        score_list[(target_seat + 2) % 4] = s_toi
        score_list[(target_seat + 3) % 4] = s_kami
        return score_list
    if isinstance(scores, list) and len(scores) == 4:
        return [int(s) for s in scores]
    return [25000, 25000, 25000, 25000]


def _forward_inference(
    hand_str: str,
    dora_indicator: str,
    round_str: str = "E1",
    honba: int = 0,
    kyotaku: int = 0,
    target_seat: int = 0,
    scores: dict[str, int] | list[int] | None = None,
    model_id: str = "distill_41b_infer",
    call_tile: str | None = None,
    response_prefix: list[dict[str, Any]] | None = None,
    response_candidates: list[dict[str, Any]] | None = None,
    tau: float | None = None,
) -> dict[str, Any] | None:
    """对当前局面构建一次 mjai 推断流程，返回两个视图共用的原始结果::

        {
            "dama":            {tile: q}   # 默听各切牌 Q (action_id < 37)
            "reach":           {tile: q}   # 立直后各切牌 Q (仅当可立直时非空)
            "reach_declare_q": float|None  # "宣告立直"动作 (action_id 37) 的 Q
        }

    失败返回 None。这是全模块唯一真正跑 engine 的地方 —— 候选生成与 Q/P 列
    都必须走这里。可立直时仍需一次宣告后的条件推断；复用消除的是候选与报表
    各自重复整套流程的开销，而非把两个决策状态合成一次神经网络调用。
    """
    try:
        import libriichi
        from simulator.kyoku_sim_win import parse_hand

        engine = get_cached_engine(model_id)
        tiles = parse_hand(hand_str)
        if len(tiles) not in (13, 14):
            return None

        score_list = _build_scores(scores, target_seat, kyotaku)

        bot = libriichi.mjai.Bot(engine, target_seat)
        bot.react(json.dumps({"type": "start_game"}))

        bakaze = round_str[0].upper() if round_str else "E"
        kyoku_num = int(round_str[1]) if len(round_str) > 1 and round_str[1].isdigit() else 1
        oya = 0

        # mjai 协议要求字牌 1z..7z 表示为 E, S, W, N, P, F, C
        mjai_dora = TO_MJAI_HONOR.get(dora_indicator, dora_indicator)
        mjai_tiles = [TO_MJAI_HONOR.get(t, t) for t in tiles]

        # 宝牌指示牌若与手牌重合导致全局该牌超过 4 张，安全替换为不冲突的指示牌（仅用于前向推断）
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

        if response_prefix:
            prefix_result = None
            for event in response_prefix:
                result = bot.react(json.dumps(event))
                if event["type"] == "dahai":
                    prefix_result = result
        else:
            bot.react(json.dumps({
                "type": "start_kyoku",
                "bakaze": bakaze,
                "kyoku": kyoku_num,
                "honba": honba,
                "kyotaku": kyotaku,
                "oya": oya,
                "dora_marker": eval_dora,
                "scores": score_list,
                "tehais": tehais,
            }))

        if call_tile:
            # A response must come from the same validated prefix as simulation.
            # Never synthesize a lone discard to make an impossible call legal.
            if not response_prefix:
                return None
            res_str = prefix_result
            if not res_str:
                return None
            res = json.loads(res_str)
            meta = res.get("meta", {})
            mask_bits = meta.get("mask_bits", 0)
            q_vals = meta.get("q_values", [])
            if not q_vals:
                return {"is_meld": True, "meld_qp": {}}

            max_q = max(q_vals)
            tau_safe = max(1e-4, float(tau))
            exps = [math.exp((q - max_q) / tau_safe) for q in q_vals]
            sum_e = sum(exps) or 1.0
            probs = [e / sum_e for e in exps]

            try:
                rank = 5 if call_tile[0] == "0" else int(call_tile[0])
                suit = call_tile[1]
            except Exception:
                rank, suit = 0, ""

            meld_qp: dict[str, dict[str, float]] = {}
            idx = 0
            for action_id in range(46):
                if (mask_bits >> action_id) & 1:
                    q = float(q_vals[idx])
                    p = float(probs[idx])
                    entry = {"q": q, "p": p}
                    if action_id == 38 and suit:  # chi_low -> [rank+1, rank+2]
                        meld_qp[f"chi:{rank+1}{suit}{rank+2}{suit}"] = entry
                    elif action_id == 39 and suit:  # chi_mid -> [rank-1, rank+1]
                        meld_qp[f"chi:{rank-1}{suit}{rank+1}{suit}"] = entry
                    elif action_id == 40 and suit:  # chi_high -> [rank-2, rank-1]
                        meld_qp[f"chi:{rank-2}{suit}{rank-1}{suit}"] = entry
                    elif action_id == 41:  # pon
                        meld_qp["pon"] = entry
                        meld_qp[f"pon:{call_tile}"] = entry
                    elif action_id == 42:  # daiminkan
                        meld_qp["daiminkan"] = entry
                    elif action_id == 45:  # pass
                        meld_qp["pass"] = entry
                    idx += 1
            if response_candidates:
                meld_qp = _meld_followup_qp(engine, target_seat, tiles, call_tile,
                                           response_prefix, response_candidates, meld_qp, tau=tau_safe)
            return {"is_meld": True, "meld_qp": meld_qp}

        res_str = bot.react(json.dumps({
            "type": "tsumo",
            "actor": target_seat,
            "pai": tsumo_tile,
        }))
        if not res_str:
            return None

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

        # 探查立直切牌 (action_id == 37)
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

        return {
            "dama": dama_discards,
            "reach": reach_discards,
            "reach_declare_q": q_map.get(37),
        }
    except Exception as exc:
        log.warning("模型前向推断失败: %s", exc)
        return None


def _build_qp_map(raw: dict[str, Any], tau: float = 0.1) -> dict[str, dict[str, float]]:
    """把原始推断结果整理成渲染层/报表用的 Q + 归一化 P 视图。"""
    if raw.get("is_meld"):
        return raw.get("meld_qp") or {}
    dama_discards = raw.get("dama") or {}
    reach_discards = raw.get("reach") or {}
    reach_declare_q = raw.get("reach_declare_q")

    first_level: list[tuple[str, float]] = [(t, q) for t, q in dama_discards.items()]
    if reach_declare_q is not None:
        first_level.append(("__reach__", reach_declare_q))
    if not first_level and not reach_discards:
        return {}

    # 若未指定 tau 则默认 1.0 (保持纯切牌评估基准一致)，由调用方显式传入
    tau_safe = max(1e-4, float(tau)) if tau is not None else 1.0
    max_q1 = max(q for _, q in first_level) if first_level else 0.0
    exps1 = [math.exp((q - max_q1) / tau_safe) for _, q in first_level]
    sum1 = sum(exps1) or 1.0
    p1 = {key: e / sum1 for (key, _), e in zip(first_level, exps1)}
    reach_p = p1.get("__reach__")

    out: dict[str, dict[str, float]] = {}
    for t, q in dama_discards.items():
        out[t] = {"q": q, "p": p1.get(t, 0.0), "riichi": 0.0}

    if reach_discards:
        max_q2 = max(reach_discards.values())
        exps2 = {t: math.exp((q - max_q2) / tau_safe) for t, q in reach_discards.items()}
        sum2 = sum(exps2.values()) or 1.0
        for t, q in reach_discards.items():
            entry = {"q": q, "p": exps2[t] / sum2, "riichi": 1.0}
            if reach_p is not None:
                entry["reach_p"] = reach_p  # 第一级"宣告立直"的归一概率
            out[f"riichi:{t}"] = entry
    return out


def _build_top_candidates(
    raw: dict[str, Any],
    min_k: int = 2,
    max_k: int = 4,
) -> list[tuple[str, bool, float]]:
    """把原始推断结果整理成"该推演哪几张"的候选视图，返回 [(tile, is_riichi, weight)]。

    每张牌取"立直 / 默听"中 Q 更高者合并成单池，再 softmax + 断崖判定自适应选前 x 个。
    """
    dama_discards = raw.get("dama") or {}
    reach_discards = raw.get("reach") or {}

    all_tiles = set(dama_discards.keys()) | set(reach_discards.keys())
    pool: list[tuple[str, bool, float]] = []
    for t in sorted(all_tiles, key=ACTION_TO_TILE.index):
        q_dama = dama_discards.get(t)
        q_reach = reach_discards.get(t)
        if q_dama is not None and q_reach is not None:
            if q_reach >= q_dama:
                pool.append((t, True, q_reach))
            else:
                pool.append((t, False, q_dama))
        elif q_reach is not None:
            pool.append((t, True, q_reach))
        elif q_dama is not None:
            pool.append((t, False, q_dama))

    if not pool:
        return []

    max_q = max(c[2] for c in pool)
    exps = [math.exp(c[2] - max_q) for c in pool]
    sum_exp = sum(exps)
    probs = [e / sum_exp for e in exps]

    sorted_pool = sorted(zip(pool, probs), key=lambda x: x[1], reverse=True)
    weights = [p for _, p in sorted_pool]

    k = select_candidate_count(weights, min_x=min_k, max_x=max_k)
    selected = [(c[0], c[1], p) for c, p in sorted_pool[:k]]

    log_details = [f"{tile}{'R' if is_riichi else ''}({p*100:.1f}%)" for tile, is_riichi, p in selected]
    log.info("模型前向推断完成，动态自适应选取前 %d 选: %s", k, ", ".join(log_details))
    return selected


def model_forward(
    hand_str: str,
    dora_indicator: str,
    round_str: str = "E1",
    honba: int = 0,
    kyotaku: int = 0,
    target_seat: int = 0,
    scores: dict[str, int] | list[int] | None = None,
    model_id: str = "distill_41b_infer",
    min_k: int = 2,
    max_k: int = 4,
    call_tile: str | None = None,
    response_prefix: list[dict[str, Any]] | None = None,
    response_candidates: list[dict[str, Any]] | None = None,
    tau: float | None = None,
) -> dict[str, Any]:
    """统一推断入口：一次前向推断同时产出 Q/P 视图与候选视图。

    返回::

        {"qp": {candidate_key: {"q":..., "p":..., "riichi":...}},
         "top": [(tile, is_riichi, weight), ...]}

    两者失败时分别为 {} / []，调用方按空值走原有降级路径即可。
    """
    raw = _forward_inference(
        hand_str=hand_str,
        dora_indicator=dora_indicator,
        round_str=round_str,
        honba=honba,
        kyotaku=kyotaku,
        target_seat=target_seat,
        scores=scores,
        model_id=model_id,
        call_tile=call_tile,
        response_prefix=response_prefix,
        response_candidates=response_candidates,
        tau=tau,
    )
    if raw is None:
        return {"qp": {}, "top": []}
    return {
        "qp": _build_qp_map(raw, tau=tau),
        "top": _build_top_candidates(raw, min_k=min_k, max_k=max_k),
    }


def eval_model_qp(
    hand_str: str,
    dora_indicator: str,
    round_str: str = "E1",
    honba: int = 0,
    kyotaku: int = 0,
    target_seat: int = 0,
    scores: dict[str, int] | list[int] | None = None,
    model_id: str = "distill_41b_infer",
    call_tile: str | None = None,
    response_prefix: list[dict[str, Any]] | None = None,
    response_candidates: list[dict[str, Any]] | None = None,
    tau: float | None = None,
) -> dict[str, dict[str, Any]]:
    """对当前局面做一次前向推断，返回每个合法切牌/副露动作的 Q 值与 Softmax 归一化 P。

    key 与 /sim 请求里 discards[].candidate 一致 (普通切牌 = 牌名，立直切牌 = "riichi:<牌名>")，
    便于渲染层直接用 candidate 取值。Q 为模型原始 advantage；P 为归一化概率，
    ΣP(默听切牌) + P(宣告立直) = 1，ΣP(切牌 | 立直后) = 1；两层不能混加。
    """
    return model_forward(
        hand_str=hand_str,
        dora_indicator=dora_indicator,
        round_str=round_str,
        honba=honba,
        kyotaku=kyotaku,
        target_seat=target_seat,
        scores=scores,
        model_id=model_id,
        call_tile=call_tile,
        response_prefix=response_prefix,
        response_candidates=response_candidates,
        tau=tau,
    )["qp"]


def get_top_model_discards(
    hand_str: str,
    dora_indicator: str,
    round_str: str = "E1",
    honba: int = 0,
    kyotaku: int = 0,
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

    注意：若调用方同时也需要 Q/P（例如报表列），请直接用 model_forward() 一次拿到
    两个视图，不要分别调用本函数与 eval_model_qp() —— 那会跑两遍完整推断。
    """
    fwd = model_forward(
        hand_str=hand_str,
        dora_indicator=dora_indicator,
        round_str=round_str,
        honba=honba,
        kyotaku=kyotaku,
        target_seat=target_seat,
        scores=scores,
        model_id=model_id,
        min_k=min_k,
        max_k=max_k,
    )
    return [(tile, is_riichi) for tile, is_riichi, _ in fwd["top"]]

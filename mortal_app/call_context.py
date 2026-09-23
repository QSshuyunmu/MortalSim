"""Response decisions at a fixed, pre-draw prefix boundary (no native imports).

Requests use engine/absolute seats; the bot translates current seat winds once.
Only closed 13-tile hands and an uninterrupted discard prefix are supported.
"""
from __future__ import annotations

from collections import Counter
import re
from typing import Any

HONORS = dict(zip([f"{i}z" for i in range(1, 8)], "ESWNPFC"))


def tile(value: str) -> str:
    value = str(value)
    reverse = {v: k for k, v in HONORS.items()}
    return reverse.get(value, {"5mr": "0m", "5pr": "0p", "5sr": "0s"}.get(value, value))


def base(value: str) -> str:
    value = tile(value)
    return "5" + value[1:] if value.startswith("0") else value


def mjai(value: str) -> str:
    value = tile(value)
    return HONORS.get(value, "5" + value[1:] + "r" if value.startswith("0") else value)


def tiles(text: str) -> list[str]:
    tokens = re.findall(r"[0-9]+[mpsz]|[ESWNPFC]", text)
    if "".join(tokens) != text:
        raise ValueError("手牌格式错误")
    return [tile(t) for tok in tokens for t in ([tok] if tok in HONORS.values() else [n + tok[-1] for n in tok[:-1]])]


def entry(item: Any) -> tuple[str, bool, bool]:
    if isinstance(item, dict):
        return tile(item["tile"]), bool(item.get("tsumogiri")), bool(item.get("is_riichi") or item.get("riichi"))
    if isinstance(item, (tuple, list)):
        return tile(item[0]), bool(item[1]) if len(item) > 1 else False, bool(item[2]) if len(item) > 2 else False
    return tile(item), False, False


def kind(candidate: Any) -> str:
    if isinstance(candidate, str):
        return candidate.split(":")[0]
    if candidate.get("pass_action"):
        return "pass"
    for key in ("chi", "pon", "daiminkan", "ron", "pass"):
        if candidate.get(key) or candidate.get("tile") == key:
            return key
    return "discard"


def latest_response_discard(
    rivers: list[list[tuple[str, bool, bool]]], oya: int, target: int, x: int,
) -> tuple[int, str]:
    """Resolve the last *actual* discard in a continuous public timeline.

    x is the target player's next turn number, not a requirement that every
    earlier seat has already discarded in that turn. A pon can interrupt any
    opponent's turn; a chi can only interrupt the immediately preceding seat.
    """
    if len(rivers) != 4 or not 0 <= target < 4 or not 0 <= oya < 4 or not 1 <= x <= 18:
        raise ValueError("响应牌河座次或巡目越界")
    if len(rivers[target]) != x - 1:
        raise ValueError(f"牌河时序错误：自家第{x}巡响应前必须已弃{x - 1}张牌")
    total = sum(len(row) for row in rivers)
    seen = [0] * 4
    for index in range(total):
        actor = (oya + index) % 4
        if seen[actor] >= len(rivers[actor]):
            raise ValueError("牌河时序错误：弃牌不构成连续的轮次前缀（禁止静默截断或补出未来弃牌）")
        seen[actor] += 1
    if not total or total > 4 * x or seen[target] != x - 1:
        raise ValueError("牌河时序错误：没有可响应的最新对手弃牌")
    actor = (oya + total - 1) % 4
    if actor == target:
        raise ValueError("牌河时序错误：最后弃牌属于自己，不能响应自己的弃牌")
    return actor, rivers[actor][-1][0]


def response_context(request: dict) -> dict | None:
    candidates = request.get("discards", [])
    if isinstance(candidates, str):
        candidates = candidates.split(",")
    kinds = [kind(c) for c in candidates]
    if not any(k in ("chi", "pon", "daiminkan", "ron", "pass") for k in kinds):
        return None
    if any(k not in ("chi", "pon", "daiminkan", "ron", "pass") for k in kinds):
        raise ValueError("不能在同一决策点混合摸牌切牌与吃/碰/过牌候选")
    hand = tiles(request["hand"])
    if len(hand) != 13 or request.get("first_tsumo") or request.get("prefix_melds"):
        raise ValueError("副露响应目前仅支持未副露的13张手牌；不能填入摸牌或省略已有副露")
    oya = int(str(request.get("round", "E1"))[1]) - 1
    target = request.get("target_seat")
    target = oya if target is None else int(target)
    wind = (target - oya) % 4
    x = int(request.get("x", 1))
    if wind == 0 and x == 1:
        raise ValueError("东家(庄家)第1巡尚无上家弃牌，不能吃/碰/过；请使用真实响应时点（如 x=2）")
    if not 0 <= target < 4 or not 1 <= x <= 18:
        raise ValueError("副露响应座次或巡目越界")
    rivers = request.get("opponent_rivers")
    if not isinstance(rivers, (list, tuple)) or len(rivers) != 4:
        raise ValueError("副露响应必须提供四家牌河，不能凭空生成响应弃牌")
    rivers = [[entry(e) for e in row] for row in rivers]
    if rivers[target]:
        raise ValueError("自家牌河只能通过 target_past_discards 提供，不能在 opponent_rivers 重复指定")
    rivers[target] = [entry(e) for e in request.get("target_past_discards") or []]
    actor, called = latest_response_discard(rivers, oya, target, x)
    if "chi" in kinds and actor != (target + 3) % 4:
        raise ValueError("吃牌只能响应上家的最新弃牌；碰牌可响应任意对手")
    visible = hand + [tile(request["dora"])] + [e[0] for row in rivers for e in row]
    if any(not re.fullmatch(r"[0-9][mps]|[1-7]z", t) for t in visible):
        raise ValueError("牌局中存在非法牌")
    counts = Counter(map(base, visible))
    if any(n > 4 for n in counts.values()) or any(visible.count(f"0{s}") > 1 or visible.count(f"5{s}") > 3 for s in "mps"):
        raise ValueError("手牌、宝牌指示和牌河存在超出物理数量的牌")
    if any(e[2] for e in rivers[target]) and any(k in ("chi", "pon", "daiminkan") for k in kinds):
        raise ValueError("立直后不能吃/碰/大明杠")
    for c, k in zip(candidates, kinds):
        if isinstance(c, str):
            c = {}
        if c.get("call_tile") and tile(c["call_tile"]) != called:
            raise ValueError(f"副露目标{c['call_tile']}与玩家{actor}最新弃牌{called}不一致")
        if k == "chi":
            consumed = [tile(t) for t in c.get("chi", [])]
            seq = sorted(map(base, consumed + [called]))
            if (len(consumed) != 2 or called[-1] not in "mps" or
                    len({t[-1] for t in seq}) != 1 or
                    [int(t[0]) for t in seq] != list(range(int(seq[0][0]), int(seq[0][0]) + 3))):
                raise ValueError(f"吃牌搭子不能与最新弃牌{called}组成顺子")
        elif k in ("pon", "daiminkan"):
            n = 2 if k == "pon" else 3
            consumed = sorted((t for t in hand if base(t) == base(called)), key=lambda t: not t.startswith("0"))[:n]
            if len(consumed) != n:
                raise ValueError(f"手牌不足以{k}最新弃牌{called}")
        else:
            consumed = []
        remaining = Counter(hand)
        remaining.subtract(consumed)
        if any(n < 0 for n in remaining.values()):
            raise ValueError("吃牌搭子不在手牌中")
        follow = c.get("follow_up_discard")
        if follow and remaining[tile(follow)] <= 0:
            raise ValueError("指定吃碰后切牌不在剩余手牌中，不能静默改为模型自动切牌")
    return {"kind": "response", "target_actor": actor, "tile": called, "target_seat": target,
            "oya": oya, "x": x, "rivers": rivers, "hand": hand}


def response_events(request: dict, context: dict) -> list[dict]:
    """Reconstruct exactly the known self hand and public prefix for Q/P/legal masks.

    Opponent hands/draws stay unknown. No synthetic self draw at the boundary.
    """
    target, oya = context["target_seat"], context["oya"]
    rivers, hand = context["rivers"], context["hand"]
    tedashi = [e[0] for e in rivers[target] if not e[1]]
    k = len(tedashi)
    if k > 13:
        raise ValueError("自家历史手切超过当前前缀重建能力")
    initial = tedashi + hand[:13-k]
    self_draws = iter(hand[13-k:])
    tehais = [["?"] * 13 for _ in range(4)]
    tehais[target] = list(map(mjai, initial))
    rel = request.get("scores") or {}
    values = [rel.get("self", 25000), rel.get("shimocha", 25000), rel.get("toimen", 25000)]
    values.append(100000 - int(request.get("kyotaku", 0)) * 1000 - sum(values))
    scores = [0] * 4
    for i, v in enumerate(values):
        scores[(target+i) % 4] = v
    events = [{"type": "start_kyoku", "bakaze": request["round"][0], "kyoku": int(request["round"][1]),
               "honba": int(request.get("honba", 0)), "kyotaku": int(request.get("kyotaku", 0)),
               "oya": oya, "scores": scores, "dora_marker": mjai(request["dora"]), "tehais": tehais}]
    for turn in range(context["x"]):
        for offset in range(4):
            p = (oya + offset) % 4
            if turn >= len(rivers[p]):
                continue
            t, ts, reach = rivers[p][turn]
            draw = (t if ts else next(self_draws)) if p == target else "?"
            events.append({"type": "tsumo", "actor": p, "pai": mjai(draw)})
            if reach:
                events.append({"type": "reach", "actor": p})
            events.append({"type": "dahai", "actor": p, "pai": mjai(t), "tsumogiri": ts})
            if reach:
                events.append({"type": "reach_accepted", "actor": p})
    return events


def validate_native_response(request: dict, context: dict) -> None:
    """Check native rules, including kuikae, before any engine/model work."""
    import json
    from libriichi.state import PlayerState

    events = response_events(request, context)
    candidates = request["discards"]
    if isinstance(candidates, str):
        candidates = candidates.split(",")
    for c in candidates:
        if isinstance(c, str):
            c = {"tile": c}
        state = PlayerState(context["target_seat"])
        for event in events:
            state.update(json.dumps(event))
        k = kind(c)
        if k == "pass":
            # Runner only stops at actionable response boundaries; never let pass
            # slide forward to a later draw/response if no response action exists.
            if not state.last_cans.can_pass:
                raise ValueError("此弃牌没有可响应动作，当前runner不能模拟独立pass")
            continue
        action = {"type": k if k != "ron" else "hora", "actor": context["target_seat"],
                  "target": context["target_actor"]}
        if k != "ron":
            action["pai"] = mjai(context["tile"])
            if k == "chi":
                consumed = c["chi"]
            else:
                consumed = sorted((t for t in context["hand"] if base(t) == base(context["tile"])), key=lambda t: not t.startswith("0"))[:2 if k == "pon" else 3]
            action["consumed"] = list(map(mjai, consumed))
        _, mask = state.encode_obs(4, False)
        if k == "chi":
            called_rank = int(base(context["tile"])[0])
            start_rank = min(int(base(t)[0]) for t in c["chi"] + [context["tile"]])
            action_id = 38 + called_rank - start_rank
        else:
            action_id = {"pon": 41, "daiminkan": 42, "ron": 43}[k]
        if not mask[action_id]:
            raise ValueError(f"原生合法动作mask不允许{k}")
        state.validate_reaction(json.dumps(action))
        if c.get("follow_up_discard"):
            state.update(json.dumps(action))
            follow = tile(c["follow_up_discard"])
            if follow[0] == "0":
                discard_id = 34 + "mps".index(follow[1])
            else:
                discard_id = {"m": 0, "p": 9, "s": 18, "z": 27}[follow[1]] + int(follow[0]) - 1
            _, discard_mask = state.encode_obs(4, False)
            if not discard_mask[discard_id]:
                raise ValueError(f"吃碰后不能切{follow}（喰替或其他合法性限制）")
            state.validate_reaction(json.dumps({"type": "dahai", "actor": context["target_seat"],
                                               "pai": mjai(follow), "tsumogiri": False}))

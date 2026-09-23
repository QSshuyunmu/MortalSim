"""精简 /sim 指令解析器：支持巡目、座次、全动作快照、吃碰副露声明与立直牌河。"""
from __future__ import annotations

import re
from typing import Any

SEAT_MAP = {
    "0": 0, "e": 0, "east": 0, "东": 0, "東": 0, "1z": 0,
    "1": 1, "s": 1, "south": 1, "南": 1, "2z": 1,
    "2": 2, "w": 2, "west": 2, "西": 2, "3z": 2,
    "3": 3, "n": 3, "north": 3, "北": 3, "4z": 3,
}

HONOR_MAP = {
    "1z": "1z", "2z": "2z", "3z": "3z", "4z": "4z", "5z": "5z", "6z": "6z", "7z": "7z",
    "东": "1z", "南": "2z", "西": "3z", "北": "4z",
    "白": "5z", "发": "6z", "發": "6z", "中": "7z",
    "e": "1z", "s": "2z", "w": "3z", "n": "4z", "p": "5z", "f": "6z", "c": "7z",
}



def dora_to_indicator(dora: str) -> str:
    """将宝牌转化为宝牌指示牌 (Dora -> Dora Indicator).
       例：8s -> 7s, 1m -> 9m, 5p/0p -> 4p, 1z(东) -> 4z(北), 5z(白) -> 7z(中).
    """
    t = dora.strip().lower()
    if t in ("0m", "5mr"):
        t = "5m"
    elif t in ("0p", "5pr"):
        t = "5p"
    elif t in ("0s", "5sr"):
        t = "5s"

    if t.endswith("m") or t.endswith("p") or t.endswith("s"):
        suit = t[1]
        num = int(t[0])
        ind_num = 9 if num == 1 else (num - 1)
        return f"{ind_num}{suit}"
    elif t.endswith("z"):
        num = int(t[0])
        if 1 <= num <= 4:
            ind_num = 4 if num == 1 else (num - 1)
            return f"{ind_num}z"
        elif 5 <= num <= 7:
            ind_num = 7 if num == 5 else (num - 1)
            return f"{ind_num}z"
    return dora

def normalize_tile_text(text: str) -> str:
    """将各种手牌写法归一化为标准的 compact 格式（如 '123m456p789s11222z'）。
    如果包含无法合法识别为麻将牌的字符或格式，返回原串或空串。
    对于单个单牌（如宝牌指示），只有符合合法的数字+花色或字牌时才属于合法牌。
    """
    t = text.strip()
    if not t:
        return ""
    if t in HONOR_MAP:
        return HONOR_MAP[t]
    if t.lower() in ("e", "s", "w", "n", "p", "f", "c"):
        return HONOR_MAP[t.lower()]
    if t.lower() in ("0m", "5mr"):
        return "0m"
    if t.lower() in ("0p", "5pr"):
        return "0p"
    if t.lower() in ("0s", "5sr"):
        return "0s"

    tokens = re.findall(r"[0-9]+[mpszMPSZ]|[东南西北白发發中]+", t)
    if tokens and "".join(tokens) == t.replace(" ", ""):
        out = []
        for tok in tokens:
            if tok[0] in "东南西北白发發中":
                for ch in tok:
                    out.append(HONOR_MAP.get(ch, ch))
            else:
                suit = tok[-1].lower()
                nums = tok[:-1]
                for n in nums:
                    out.append(f"{n}{suit}")
        return "".join(out)

    # 检查是否全部字符都能被麻将语法解释
    compact_matches = re.findall(r"[0-9]+[mpszMPSZ]|[东南西北白发發中]+", t)
    if compact_matches:
        parsed_len = sum(len(m) for m in compact_matches)
        cleaned_t = t.replace(" ", "").replace(",", "").replace("，", "")
        if parsed_len == len(cleaned_t):
            out = []
            for tok in compact_matches:
                if tok[0] in "东南西北白发發中":
                    for ch in tok:
                        out.append(HONOR_MAP.get(ch, ch))
                else:
                    suit = tok[-1].lower()
                    nums = tok[:-1]
                    for n in nums:
                        out.append(f"{n}{suit}")
            return "".join(out)

    explicit = re.findall(r"[0-9][mpszMPSZ]|[东南西北白发發中]", t)
    if explicit:
        parsed_len = sum(len(m) for m in explicit)
        cleaned_t = t.replace(" ", "")
        if parsed_len == len(cleaned_t):
            out = []
            for item in explicit:
                if item in HONOR_MAP:
                    out.append(HONOR_MAP[item])
                else:
                    out.append(item.lower())
            return "".join(out)

    return t


def _infer_chi_consumed(hand_tiles: list[str], call_tile: str) -> list[list[str]]:
    """Return the possible two in-hand tiles for a called suited tile.

    A one-tile chi form such as ``chi:1m>9s`` names the tile discarded by
    the opponent; the two tiles consumed from our hand are inferred here.
    Red fives (``0m``/``0p``/``0s``) can satisfy a normal five in a sequence.
    """
    if len(call_tile) != 2 or call_tile[1] not in ("m", "p", "s"):
        return []
    try:
        called_rank = 5 if call_tile[0] == "0" else int(call_tile[0])
    except ValueError:
        return []
    if called_rank not in range(1, 10):
        return []

    from collections import Counter
    import itertools

    available = Counter(hand_tiles)
    matches: list[list[str]] = []
    for start in range(1, 8):
        sequence = [start, start + 1, start + 2]
        if called_rank not in sequence:
            continue
        # 每个待补牌位的可选牌：数字 5 同时存在普通五与赤五两种选择，
        # 二者是不同的实体牌 -> 必须展开成独立候选（赤五多一番打点）。
        options: list[list[str]] = []
        valid = True
        for rank in sequence:
            if rank == called_rank:
                continue
            normal = f"{rank}{call_tile[1]}"
            red = f"0{call_tile[1]}"
            choices: list[str] = []
            if available[normal] > 0:
                choices.append(normal)
            if rank == 5 and available[red] > 0:
                choices.append(red)
            if not choices:
                valid = False
                break
            options.append(choices)
        if not valid:
            continue
        for combo in itertools.product(*options):
            consumed = list(combo)
            need = Counter(consumed)
            # 同一张实体牌不能被同时用两次（例如只剩一张 5m 时不能用两次 5m）
            if any(need[tile] > available[tile] for tile in need):
                continue
            if consumed not in matches:
                matches.append(consumed)
        continue
    return matches


def _parse_river_token(token: str) -> tuple[str, bool, bool, dict[str, Any] | None] | None:
    """Parse one discard token like '1z', '2zt', '3pr', '4z(南吃23m)'
       -> (tile, is_tsumogiri, is_riichi, meld_dict | None).
    """
    t = token.strip()
    if not t:
        return None

    meld_info = None
    m_meld = re.search(r'[\(（]([东南西北0-3eswnESWN])?(吃|碰|杠|chi|pon|kan)?([0-9mpsz]*)?[\)）]', t)
    if m_meld:
        actor_tok = (m_meld.group(1) or "").lower()
        meld_type = (m_meld.group(2) or "").lower()
        consumed_str = m_meld.group(3) or ""
        t = t[:m_meld.start()] + t[m_meld.end():]
        actor_seat = SEAT_MAP.get(actor_tok, None)
        meld_info = {
            "actor": actor_seat,
            "type": "chi" if meld_type in ("吃", "chi") else ("pon" if meld_type in ("碰", "pon") else "minkan"),
            "consumed": [consumed_str[i:i+2] for i in range(0, len(consumed_str), 2)] if consumed_str else [],
        }

    is_tsumogiri = False
    is_riichi = False
    while len(t) > 2 and (t[-1] in ('^', 't', 'T', '摸', 'r', 'R', '立')):
        if t[-1] in ('^', 't', 'T', '摸'):
            is_tsumogiri = True
            t = t[:-1].rstrip("摸")
        elif t[-1] in ('r', 'R', '立'):
            is_riichi = True
            t = t[:-1].rstrip("立")
    norm = normalize_tile_text(t)
    if len(norm) != 2:
        return None
    return norm, is_tsumogiri, is_riichi, meld_info


def _parse_river_tokens_string(discards_raw: str, *, strict: bool = False) -> list[tuple[str, bool, bool, dict[str, Any] | None]]:
    """Parse comma/space/compact separated tile tokens."""
    discards_raw = discards_raw.strip()
    if not discards_raw:
        return []
    if any(sep in discards_raw for sep in (",", "，", "、", " ", "  ")):
        raw_tokens = [d.strip() for d in re.split(r'[,，、\s]+', discards_raw) if d.strip()]
    else:
        raw_tokens = re.findall(r'[0-9][mpsz][tT\^摸rR立]{0,2}|[1-7]z[tT\^摸rR立]{0,2}|[东南西北白发中][tT\^摸rR立]{0,2}', discards_raw)
        if strict and "".join(raw_tokens) != discards_raw:
            raise ValueError(f"显式牌河含无法解析的舍牌：{discards_raw}")

    out = []
    for tok in raw_tokens:
        parsed = _parse_river_token(tok)
        if strict and parsed is None:
            raise ValueError(f"显式牌河含无法解析的舍牌：{tok}")
        if parsed:
            out.append(parsed)
    return out


def _parse_river_spec(river_raw: str, target_seat: int, x: int = 1, oya: int = 0, *, strict: bool = False) -> tuple[list[tuple[str, bool, bool]], list[list[tuple[str, bool, bool]]] | None, list[dict[str, Any]], str | None]:
    opponent_rivers: list[list[tuple[str, bool, bool]]] = [[], [], [], []]
    target_past: list[tuple[str, bool, bool]] = []
    melds: list[dict[str, Any]] = []
    river_raw = river_raw.strip()

    # 1. 检查是否存在按座位命名的分段（如 东:1m,2p / 南:9s 或 0:1m 1:2p）
    seat_name_pattern = r"东|南|西|北|0|1|2|3|[eswnESWN]"
    splits = list(re.finditer(rf'(?:^|[;；/|／｜\s,，])(?=({seat_name_pattern})[:：=])', river_raw))
    if splits:
        indices = [m.end() for m in splits]
        indices.append(len(river_raw))
        sections = []
        for i in range(len(indices) - 1):
            sec = river_raw[indices[i]:indices[i+1]].strip().rstrip(';；/|／｜,， ')
            if sec:
                sections.append(sec)

        if strict and (len(sections) != 4 or indices[0] != 0):
            return [], None, [], "显式响应牌河必须完整指定四家（东/南/西/北），缺失座位不能自动补牌"
        seen_seats: set[int] = set()
        for sec in sections:
            parts = re.split(r'[:：=]', sec, maxsplit=1)
            if len(parts) != 2:
                continue
            seat_token = parts[0].strip().lower()
            if seat_token not in SEAT_MAP:
                return [], None, [], f"未知座位编号 '{parts[0]}'，支持 0-3 / E,S,W,N / 东南西北"
            seat_idx = SEAT_MAP[seat_token]
            if strict and seat_idx in seen_seats:
                return [], None, [], "显式响应牌河不能重复指定同一家座位"
            seen_seats.add(seat_idx)
            tokens = _parse_river_tokens_string(parts[1], strict=strict)
            for tok in tokens:
                tile_s, ts, is_r, m_info = tok
                if m_info:
                    m_info["target"] = seat_idx
                    m_info["pai"] = tile_s
                    melds.append(m_info)
                if seat_idx == target_seat:
                    target_past.append((tile_s, ts, is_r))
                else:
                    opponent_rivers[seat_idx].append((tile_s, ts, is_r))

        if strict and seen_seats != set(range(4)):
            return [], None, [], "显式响应牌河必须指定四家不同座位"
        has_opp = any(len(r) > 0 for i, r in enumerate(opponent_rivers) if i != target_seat)
        return target_past, opponent_rivers if has_opp else None, melds, None

    # 2. 无命名分段：按斜杠 '/' 分隔
    slash_sections = [s.strip() for s in re.split(r'[/|／｜]+', river_raw) if s.strip()]
    if len(slash_sections) == 4:
        for seat_idx, sec in enumerate(slash_sections):
            tokens = _parse_river_tokens_string(sec, strict=strict)
            for tok in tokens:
                tile_s, ts, is_r, m_info = tok
                if m_info:
                    m_info["target"] = seat_idx
                    m_info["pai"] = tile_s
                    melds.append(m_info)
                if seat_idx == target_seat:
                    target_past.append((tile_s, ts, is_r))
                else:
                    opponent_rivers[seat_idx].append((tile_s, ts, is_r))
        has_opp = any(len(r) > 0 for i, r in enumerate(opponent_rivers) if i != target_seat)
        return target_past, opponent_rivers if has_opp else None, melds, None
    elif len(slash_sections) < 4:
        if strict:
            return [], None, [], "显式响应牌河必须完整指定四家（东/南/西/北），缺失座位不能自动补牌"
        prec_seats = []
        cur = oya
        while cur != target_seat:
            prec_seats.append(cur)
            cur = (cur + 1) % 4
        if len(slash_sections) == len(prec_seats) and len(prec_seats) > 0:
            assigned_seats = prec_seats
        else:
            assigned_seats = list(range(len(slash_sections)))

        for idx, seat_idx in enumerate(assigned_seats):
            tokens = _parse_river_tokens_string(slash_sections[idx])
            for tok in tokens:
                tile_s, ts, is_r, m_info = tok
                if m_info:
                    m_info["target"] = seat_idx
                    m_info["pai"] = tile_s
                    melds.append(m_info)
                if seat_idx == target_seat:
                    target_past.append((tile_s, ts, is_r))
                else:
                    opponent_rivers[seat_idx].append((tile_s, ts, is_r))
        has_opp = any(len(r) > 0 for i, r in enumerate(opponent_rivers) if i != target_seat)
        return target_past, opponent_rivers if has_opp else None, melds, None

    return [], None, [], f"牌河分段数量 ({len(slash_sections)}) 超过四家总数 (4)"



def _generate_default_rivers(
    hand_tiles: list[str],
    target_seat: int,
    oya: int,
    x: int,
    call_target_tile: str | None = None,
    partial_target_past: list[tuple[str, bool, bool]] | None = None,
    partial_opp_rivers: list[list[tuple[str, bool, bool]]] | None = None,
) -> tuple[list[tuple[str, bool, bool]], list[list[tuple[str, bool, bool]]]]:
    """当巡目 x >= 2 且用户未提供牌河时，自动生成四家物理合法、无冲突且符合牌理的牌河。

    抽样规则（按用户口径）：
      1. 先剔除自己手牌及周边相关联牌（±1 邻张/进张），手中字牌绝对不出现；
      2. 权重分层：字牌与无关联幺九 = 1.0，28 数牌 = 1/5，37 = 1/25，456 = 1/125；
      3. 用确定性 RNG（同一局面同一牌河，便于复盘），避免“每次都切同一张”的死板牌河；
      4. 第一巡四家不打相同牌，避免四风连打；若指定副露目标牌，则目标玩家的上家在
         决策巡的上一舍必为该牌（保持响应时点因果正确）。
    """
    import hashlib
    import random

    seed_material = "|".join(
        sorted(hand_tiles)
        + [f"oya{oya}", f"seat{target_seat}", f"x{x}", f"call{call_target_tile or ''}"]
    )
    rng = random.Random(int.from_bytes(hashlib.sha256(seed_material.encode()).digest()[:8], "big"))

    def _tile_weight(t: str) -> float:
        if t in ("0m", "5mr"): t = "5m"
        elif t in ("0p", "5pr"): t = "5p"
        elif t in ("0s", "5sr"): t = "5s"
        if t.endswith("z"):
            return 1.0
        n = int(t[0])
        if n in (1, 9):
            return 1.0
        if n in (2, 8):
            return 0.2
        if n in (3, 7):
            return 0.04
        return 0.008
    forbidden = set()
    for t in hand_tiles:
        if t in ("0m", "5mr"):
            t = "5m"
        elif t in ("0p", "5pr"):
            t = "5p"
        elif t in ("0s", "5sr"):
            t = "5s"
        forbidden.add(t)
        if t.endswith("z"):
            continue
        suit = t[-1]
        num = int(t[0])
        # 排除邻张与搭子进张 (num-1, num+1)
        if num > 1:
            forbidden.add(f"{num-1}{suit}")
        if num < 9:
            forbidden.add(f"{num+1}{suit}")

    # 优先级出牌池：字牌 -> 幺九 (1,9) -> 28 -> 37 -> 456
    TILES_BY_PRIORITY = (
        ["1z", "2z", "3z", "4z", "5z", "6z", "7z"] +
        ["1m", "9m", "1p", "9p", "1s", "9s"] +
        ["2m", "8m", "2p", "8p", "2s", "8s"] +
        ["3m", "7m", "3p", "7p", "3s", "7s"] +
        ["4m", "6m", "5m", "4p", "6p", "5p", "4s", "6s", "5s"]
    )
    allowed_pool = [t for t in TILES_BY_PRIORITY if t not in forbidden]

    tile_used_counts: dict[str, int] = {}
    for t in hand_tiles:
        if t in ("0m", "5mr"):
            t = "5m"
        elif t in ("0p", "5pr"):
            t = "5p"
        elif t in ("0s", "5sr"):
            t = "5s"
        tile_used_counts[t] = tile_used_counts.get(t, 0) + 1

    rivers: list[list[tuple[str, bool, bool]]] = [[], [], [], []]
    if partial_target_past:
        rivers[target_seat] = list(partial_target_past)
    if partial_opp_rivers:
        for p in range(4):
            if p != target_seat and p < len(partial_opp_rivers):
                rivers[p] = list(partial_opp_rivers[p] or [])

    # 预先将用户已指定牌河中的牌计入使用计数
    for p in range(4):
        for tok in rivers[p]:
            t = tok[0]
            if t in ("0m", "5mr"): t = "5m"
            elif t in ("0p", "5pr"): t = "5p"
            elif t in ("0s", "5sr"): t = "5s"
            tile_used_counts[t] = tile_used_counts.get(t, 0) + 1

    # 每张牌被各家切出的历史记录（避免一家频繁来回切相同牌）
    player_discard_history: list[list[str]] = [[tok[0] for tok in rivers[p]] for p in range(4)]

    def pick_tile_for_player(p_idx: int, turn_idx: int, used_this_turn: set[str]) -> str:
        # 该玩家上一巡打出的牌（严禁连续手切同一张牌）
        last_discard = rivers[p_idx][-1][0] if rivers[p_idx] else None

        def can_pick(candidate: str) -> bool:
            if tile_used_counts.get(candidate, 0) >= 4:
                return False
            if last_discard is not None and candidate == last_discard:
                return False
            if turn_idx == 1 and candidate in used_this_turn:
                return False
            return True

        def weighted_choice(cands: list[str]) -> str:
            weights = [_tile_weight(c) for c in cands]
            return rng.choices(cands, weights=weights, k=1)[0]

        valid_candidates = [t for t in allowed_pool if can_pick(t)]
        if valid_candidates:
            best_tile = weighted_choice(valid_candidates)
            tile_used_counts[best_tile] = tile_used_counts.get(best_tile, 0) + 1
            used_this_turn.add(best_tile)
            player_discard_history[p_idx].append(best_tile)
            return best_tile

        # 候选不足时，从全局合法牌池补充
        valid_fallback = [t for t in TILES_BY_PRIORITY if t not in hand_tiles and can_pick(t)]
        if valid_fallback:
            best_tile = weighted_choice(valid_fallback)
            tile_used_counts[best_tile] = tile_used_counts.get(best_tile, 0) + 1
            used_this_turn.add(best_tile)
            player_discard_history[p_idx].append(best_tile)
            return best_tile

        # 终极保底：未满 4 张且非上一打
        final_pool = [t for t in TILES_BY_PRIORITY if tile_used_counts.get(t, 0) < 4 and (last_discard is None or t != last_discard)]
        if final_pool:
            picked = weighted_choice(final_pool)
            tile_used_counts[picked] = tile_used_counts.get(picked, 0) + 1
            used_this_turn.add(picked)
            player_discard_history[p_idx].append(picked)
            return picked

        fallback = "2z" if last_discard == "1z" else "1z"
        tile_used_counts[fallback] = tile_used_counts.get(fallback, 0) + 1
        used_this_turn.add(fallback)
        player_discard_history[p_idx].append(fallback)
        return fallback

    pos_target = (target_seat + 4 - oya) % 4

    for r in range(1, x + 1):
        used_this_turn: set[str] = set()
        for offset in range(4):
            p = (oya + offset) % 4
            pos_p = offset
            if r == x and pos_p == pos_target:
                break
            if r == x and pos_p > pos_target:
                continue

            # 若玩家 p 在此巡已有用户指定的舍牌，则直接沿用，不重复生成
            if len(rivers[p]) >= r:
                t = rivers[p][r - 1][0]
                norm_t = "5m" if t in ("0m", "5mr") else ("5p" if t in ("0p", "5pr") else ("5s" if t in ("0s", "5sr") else t))
                used_this_turn.add(norm_t)
                continue

            # 吃/碰目标牌必须落在目标玩家真正能响应的上一张舍牌上。
            # 目标玩家若是本巡第一家，则该牌来自上一巡末家；否则来自本巡目标玩家前一家。
            call_round = x - 1 if pos_target == 0 else x
            call_player = (oya + 3) % 4 if pos_target == 0 else (oya + pos_target - 1) % 4
            if call_target_tile and r == call_round and p == call_player:
                tile = call_target_tile
                tile_used_counts[tile] = tile_used_counts.get(tile, 0) + 1
                used_this_turn.add(tile)
            else:
                tile = pick_tile_for_player(p, r, used_this_turn)
            rivers[p].append((tile, False, False))

    target_past = rivers[target_seat]
    opp_rivers = [rivers[p] if p != target_seat else [] for p in range(4)]
    return target_past, opp_rivers

def parse_sim_command(message: str) -> tuple[dict[str, Any] | None, str | None]:
    """解析精简 /sim 指令。"""
    raw = message.strip()
    if raw.startswith(("/sim", "sim")):
        raw = re.sub(r"^/sim\s*|^sim\s*", "", raw).strip()

    rest = raw

    # 0. 模型切换 m= (默认均衡, m=agg -> 激进; 仅在内部使用模型ID，绝不对外显示)
    model_id_val = "model_balanced"
    model_m = re.search(r'(?i)(?:^|(?<=[\s,;]))(?:m|模型)[:：=]?([a-zA-Z0-9_\u4e00-\u9fa5]+)\b', rest)
    if model_m:
        m_tok = model_m.group(1).lower().strip()
        if m_tok in ("agg", "aggressive", "active", "aggr", "nva", "激进", "进攻", "争一"):
            model_id_val = "model_aggressive"
        rest = rest[:model_m.start()] + " " + rest[model_m.end():]

    # 1. 提取巡目 x (支持 1..18)
    x_val = 1
    x_m = re.search(r"(?i)(?:^|(?<=[\s,;]))x[:：=]?(\d{1,2})\b", rest)
    if x_m:
        x_val = int(x_m.group(1))
        if not (1 <= x_val <= 18):
            return None, f"巡目参数 x 不合法：{x_val}（必须在 1..18 范围内）"
        rest = rest[:x_m.start()] + " " + rest[x_m.end():]

    # 2. 提取自身座位 seat
    target_seat_val = None
    seat_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:seat|座位)[:：=]?([0-3]|east|south|west|north|[eswn东南西北])\b", rest)
    if seat_m:
        s_tok = seat_m.group(1).lower()
        if s_tok in SEAT_MAP:
            target_seat_val = SEAT_MAP[s_tok]
        rest = rest[:seat_m.start()] + " " + rest[seat_m.end():]

    # 3. 提取温度 tau / T (默认 0.1)
    tau_val = 0.1
    tau_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:tau|温度|t)[:：=]?(\d+(?:\.\d+)?)\b", rest)
    if tau_m:
        tau_val = float(tau_m.group(1))
        rest = rest[:tau_m.start()] + " " + rest[tau_m.end():]

    # 4. 提取显式供托 kyotaku (支持 kyotaku=1, kt=1, 供托=1, 场供=1, 1供, 1供托, 1000供托 等)
    kyotaku_explicit = None
    kt_m = re.search(r'(?i)(?:^|(?<=[\s,;]))(?:kyotaku|kt|供托|场供|场存供托|立直棒)[:：=]?(\d+(?:k|000)?)\b', rest)
    if not kt_m:
        kt_m = re.search(r'(?i)(?:^|(?<=[\s,;]))(\d+)(?:供|供托|根立直棒)\b', rest)
    if kt_m:
        kt_str = (kt_m.group(1) or "").lower()
        if kt_str.endswith("k"):
            kyotaku_explicit = int(float(kt_str[:-1]))
        else:
            v = int(kt_str)
            if v >= 1000 and v % 1000 == 0:
                v //= 1000
            kyotaku_explicit = v
        rest = rest[:kt_m.start()] + " " + rest[kt_m.end():]

    # 4.1 提取局、本场与三段式供托 (支持 E1, E1-0, E1-3-1, S4-1-2, 东1-0-1 等)
    ROUND_CHAR_MAP = {
        "东": "E", "南": "S", "西": "W", "北": "W",
        "E": "E", "S": "S", "W": "W", "N": "W",
        "e": "E", "s": "S", "w": "W", "n": "W",
    }
    round_raw = "E1"
    honba_raw = "0"
    kyotaku_from_round = None
    round_m = re.search(r'(?i)(?:^|(?<=[\s,;]))([EWSews东南西北][1-4]局?)(?:-(\d+)(?:-(\d+))?)?(?=\s|[,;]|$|\b)', rest)
    if round_m:
        r_str = round_m.group(1).replace("局", "")
        w_char = ROUND_CHAR_MAP.get(r_str[0], "E")
        round_raw = f"{w_char}{r_str[1]}"
        honba_raw = round_m.group(2) or "0"
        if round_m.group(3) is not None:
            k_val = int(round_m.group(3))
            if k_val >= 1000 and k_val % 1000 == 0:
                k_val //= 1000
            kyotaku_from_round = k_val
        rest = rest[:round_m.start()] + " " + rest[round_m.end():]

    kyotaku_val = kyotaku_explicit if kyotaku_explicit is not None else (kyotaku_from_round if kyotaku_from_round is not None else 0)

    # 5. 提取宝牌 d... (支持 d8p, d4m, d东, d白 等)
    dora_m = re.search(r'(?i)(?:^|(?<=[\s,;]))[dD][:：\s]?([0-9mpszrKR]{2,4}|[东南西北白发發中])\b', rest)
    if not dora_m:
        dora_m = re.search(r'(?i)(?:^|(?<=[\s,;]))[dD][:：\s]?([0-9mpszrKR]{2,4}|[东南西北白发發中])', rest)
    if not dora_m:
        return None, "缺少宝牌参数，例：d8p 或 d4m"
    dora_raw = dora_m.group(1).strip()
    rest = rest[:dora_m.start()] + " " + rest[dora_m.end():]

    # 6. 提取牌河 river
    river_raw = None
    river_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:river|河|牌河)[:：=]?([0-9mpszzt\^rR立\(（\)）\u4e00-\u9fa5,，:：;；/|／｜\s\-_东南西北ESWN]+?)(?=\s+[pPdDcCeEwWsSxX]|\s+(?:runs?|局数)[:：=]?\d+|\s+\d+\b|\s*$)", rest)
    if river_m:
        river_raw = river_m.group(1).strip()
        rest = rest[:river_m.start()] + " " + rest[river_m.end():]
    elif re.search(r"(?i)(?:^|(?<=[\s,;]))(?:river|河|牌河)[:：=]", rest):
        return None, "显式牌河含无法解析的舍牌或字符"

    # 7. 提取候选 c... (支持 c=... 或 ctsumo,...)
    cand_m = re.search(r'(?i)(?:^|(?<=[\s,;]))[cC][:：=]?([a-zA-Z0-9mpszkrKR>:\-_,，、\(\)（）@\u4e00-\u9fa5]+?)(?=\s+[pPdDeEwWsSxX]|\s+\d+\b|\s*$)', rest)
    cand_raw = None
    if cand_m:
        cand_raw = cand_m.group(1).strip()
        rest = rest[:cand_m.start()] + " " + rest[cand_m.end():]

    # 8. 提取点数 (支持 P250,250,250,250 / P25000,25000 / 无P前缀的 4 段点数如 62,526,304,108)
    scores_raw = None
    scores_m = re.search(r'(?i)(?:[pP点点数][:：\s]?\s*((?:-?\d+(?:\.\d+)?k?[\s,，、]+){3}-?\d+(?:\.\d+)?k?)\b|(?<![0-9a-zA-Z])((?:-?\d+(?:\.\d+)?k?[\s,，、]+){3}-?\d+(?:\.\d+)?k?)(?![0-9a-zA-Z]))', rest)
    if scores_m:
        scores_raw = (scores_m.group(1) or scores_m.group(2)).strip()
        rest = rest[:scores_m.start()] + " " + rest[scores_m.end():]

    scores_val = None
    if scores_raw:
        scores_parts = [s.strip().lower() for s in re.split(r'[,，、\s]+', scores_raw) if s.strip()]
        if len(scores_parts) == 4:
            try:
                parsed_scores = []
                for p in scores_parts:
                    if p.endswith("k"):
                        val = int(float(p[:-1]) * 1000)
                    else:
                        val = int(float(p))
                        if abs(val) < 1000:
                            val *= 100
                    parsed_scores.append(val)
                # 若用户未显式指定供托，四家点数总和与 100000 恰相差整千点（如 99000），自动推导场存供托
                if kyotaku_explicit is None and kyotaku_from_round is None and kyotaku_val == 0:
                    pts_diff = 100000 - sum(parsed_scores)
                    if 0 < pts_diff <= 20000 and pts_diff % 1000 == 0:
                        kyotaku_val = pts_diff // 1000

                target_p = target_seat_val if target_seat_val is not None else 0
                rel_self = parsed_scores[target_p]
                rel_shimo = parsed_scores[(target_p + 1) % 4]
                rel_toimen = parsed_scores[(target_p + 2) % 4]
                scores_val = {"self": rel_self, "shimocha": rel_shimo, "toimen": rel_toimen}
            except Exception:
                return None, f"点数格式错误：{scores_raw}（支持 P180,200,390,230 或 P18k,20k,39k,23k）"

    # 9. 提取模拟局数 (支持 runs=100 / 局数:100 / 尾随数字 10 等)
    runs_raw = 500
    runs_named_m = re.search(r'(?i)(?:^|(?<=[\s,;]))(?:runs?|局数|次数)[:：=]?(\d{1,6})\b', rest)
    if runs_named_m:
        runs_raw = int(runs_named_m.group(1))
        rest = rest[:runs_named_m.start()] + " " + rest[runs_named_m.end():]
    else:
        runs_trail_m = re.search(r'(?:^|\s+)(\d{1,6})\s*$', rest)
        if runs_trail_m:
            runs_raw = int(runs_trail_m.group(1))
            rest = rest[:runs_trail_m.start()] + " " + rest[runs_trail_m.end():]

    # 10. 主手牌
    # 6. 主手牌
    hand_raw = rest.strip()
    if not hand_raw:
        return None, "未找到手牌内容，请输入 13 或 14 张手牌。"

    hand_norm = normalize_tile_text(hand_raw)
    hand_tiles = [hand_norm[i:i+2] for i in range(0, len(hand_norm), 2)]
    if len(hand_tiles) not in (1, 2, 4, 5, 7, 8, 10, 11, 13, 14):
        return None, f"手牌张数不合法（必须为 3n+1 或 3n+2 张），当前识别 {len(hand_tiles)} 张：{hand_norm or '(未识别)'}"

    dora_norm = normalize_tile_text(dora_raw)
    valid_suits = ("m", "p", "s", "z")
    is_valid_tile = (
        len(dora_norm) == 2
        and dora_norm[1] in valid_suits
        and (
            (dora_norm[1] in ("m", "p", "s") and dora_norm[0] in "0123456789")
            or (dora_norm[1] == "z" and dora_norm[0] in "1234567")
        )
    )
    if not is_valid_tile:
        return None, f"宝牌格式错误：{dora_raw}，应为 1 张合法麻将牌（如 d8p、d4m、d5z、d南 等）。"
    # 用户输入 d<宝牌>，将其转换为对应的宝牌指示牌 (dora_marker)
    dora_indicator = dora_to_indicator(dora_norm)

    candidates = []
    # 严格规则校验 1: 单牌数量上限 (全局同种牌不能超过 4 张)
    from collections import Counter
    hand_counts = Counter(hand_tiles)
    for tile_name, cnt in hand_counts.items():
        base_t = normalize_tile_text(tile_name)
        if cnt > 4:
            return None, f"手牌违背规则：同种牌【{base_t}】在手牌中出现了 {cnt} 张（麻将中同种牌最多 4 张）"

    effective_target_seat = target_seat_val if target_seat_val is not None else 0

    # 无 c= 时由模型推断决定候选；同一次推断的 Q/P 结果一并缓存进 request["_model_qp"]，
    # bot.execute 会直接复用，不再为报表列跑第二遍推断。
    precomputed_qp: dict[str, dict[str, float]] | None = None
    if cand_raw is None:
        # 当用户未提供 c 候选时，调用 Mortal 模型前向推断：支持立直切牌与无压倒性差异时的自适应 x 选 (x>=2)
        # 模型入口语义与上游一致：仅识别两个别名，其余值一律落到默认模型。
        from model_eval import model_forward
        real_model_id = "distill_nova" if model_id_val == "model_aggressive" else "distill_41b_infer"
        fwd = model_forward(
            hand_str=hand_norm,
            dora_indicator=dora_indicator,
            round_str=round_raw,
            honba=int(honba_raw),
            kyotaku=int(kyotaku_val),
            target_seat=effective_target_seat,
            scores=scores_val,
            model_id=real_model_id,
            min_k=2,
            max_k=4,
        )
        # 空结果也记录：推断已尝试，不应在报表阶段再次运行同一条失败路径。
        precomputed_qp = fwd.get("qp") or {}
        model_candidates = fwd.get("top") or []
        if model_candidates:
            for tile, is_riichi, _weight in model_candidates:
                c_name = f"riichi:{tile}" if is_riichi else tile
                candidates.append({"tile": tile, "riichi": is_riichi, "kan": False, "candidate": c_name})
        else:
            # 兜底保底策略
            unique_hand = list(dict.fromkeys(hand_tiles))
            for tile in unique_hand[:2]:
                candidates.append({"tile": tile, "riichi": False, "kan": False, "candidate": tile})
    else:
        for part in re.split(r'[,，、\s]+', cand_raw):
            if not part:
                continue
            if part in ("tsumo", "自摸", "tm"):
                candidates.append({"tile": "tsumo", "riichi": False, "kan": False, "kyushu": False, "tsumo": True, "ron": False, "pass": False})
                continue
            if part in ("ron", "荣和", "胡", "和"):
                candidates.append({"tile": "ron", "riichi": False, "kan": False, "kyushu": False, "tsumo": False, "ron": True, "pass": False})
                continue
            if part in ("pass", "见逃", "过", "不鸣"):
                candidates.append({"tile": "pass", "riichi": False, "kan": False, "kyushu": False, "tsumo": False, "ron": False, "pass": True})
                continue
            if part == "kk":
                kinds = _kyushu_kinds(hand_tiles)
                if kinds < 9:
                    return None, f"九種九牌（kk）不合法：手牌只有 {kinds} 种幺九牌（需要 9 种及以上）。"
                candidates.append({"tile": "kk", "riichi": False, "kan": False, "kyushu": True})
                continue
            if re.match(r'(?i)^(?:chi|吃)[:：]?', part):
                # 支持格式：
                # 1. 单目标牌（自动展开或推导）：chi:4m>9s / chi1m>9s / 吃4m>9s
                # 2. 复合指定（搭子+目标）：chi:23m(4m)>9s / chi:23m@4m>9s / chi4m:23m>9s
                # 3. 显式手牌搭子：chi:23m>9s / chi:35m>9s（嵌张自动推导中间牌）
                m_chi = re.match(r'(?i)^(?:chi|吃)[:：]?(.*)$', part)
                sub = (m_chi.group(1) if m_chi else "").strip()
                fu_tile = None
                if ">" in sub:
                    c_part, fu_part = sub.split(">", 1)
                    fu_norm = normalize_tile_text(fu_part)
                    if len(fu_norm) != 2:
                        return None, f"吃牌后切牌格式错误：{fu_part}"
                    fu_tile = fu_norm
                    sub = c_part.strip()

                call_tile = None
                # 提取 (4m) 或 @4m
                m_call = re.search(r'[\(@\[（]([0-9mpsz]{2})[\)\]）]|@([0-9mpsz]{2})', sub)
                if m_call:
                    raw_ct = m_call.group(1) or m_call.group(2)
                    norm_ct = normalize_tile_text(raw_ct)
                    if len(norm_ct) == 2:
                        call_tile = norm_ct
                    sub = sub[:m_call.start()] + sub[m_call.end():]
                    sub = sub.strip()

                # 提取前缀被吃牌 4m:23m
                m_pre = re.match(r'^([0-9mpsz]{2})[:：](.*)$', sub)
                if m_pre:
                    norm_ct = normalize_tile_text(m_pre.group(1))
                    if len(norm_ct) == 2:
                        call_tile = norm_ct
                    sub = m_pre.group(2).strip()

                consumed_norm = normalize_tile_text(sub)
                c_tiles = [consumed_norm[i:i+2] for i in range(0, len(consumed_norm), 2)]

                if len(c_tiles) == 1:
                    # 单张目标牌：从手牌中推导所有可能组合
                    target_t = c_tiles[0]
                    matches = _infer_chi_consumed(hand_tiles, target_t)
                    if not matches:
                        return None, f"吃牌错误：手牌中无法用两张牌吃【{target_t}】（当前手牌：{''.join(hand_tiles)}）"
                    for m in matches:
                        chi_cand_name = f"chi:{''.join(m)}"
                        if fu_tile:
                            chi_cand_name += f">{fu_tile}"
                        candidates.append({
                            "tile": "chi",
                            "riichi": False,
                            "kan": False,
                            "kyushu": False,
                            "chi": m,
                            "call_tile": target_t,
                            "follow_up_discard": fu_tile,
                            "candidate": chi_cand_name,
                        })
                    continue

                if len(c_tiles) == 2:
                    # 若未显式指定目标牌，且两张牌为同花色嵌张（如 3m 与 5m），自动推导中间被吃牌
                    if not call_tile and c_tiles[0][1] == c_tiles[1][1] and c_tiles[0][1] in ("m", "p", "s"):
                        try:
                            r1 = 5 if c_tiles[0][0] == "0" else int(c_tiles[0][0])
                            r2 = 5 if c_tiles[1][0] == "0" else int(c_tiles[1][0])
                            if abs(r1 - r2) == 2:
                                mid_rank = (r1 + r2) // 2
                                call_tile = f"{mid_rank}{c_tiles[0][1]}"
                        except Exception:
                            pass

                    chi_candidate = f"chi:{''.join(c_tiles)}"
                    if fu_tile:
                        chi_candidate += f">{fu_tile}"
                    candidates.append({
                        "tile": "chi",
                        "riichi": False,
                        "kan": False,
                        "kyushu": False,
                        "chi": c_tiles,
                        "call_tile": call_tile,
                        "follow_up_discard": fu_tile,
                        "candidate": chi_candidate,
                    })
                    continue

                return None, f"吃牌候选格式错误：{part}，例：chi:4m>9s、chi:35m>9s 或 chi:23m(4m)>9s"

            if part.startswith("pon") or part.startswith("碰"):
                # 支持：
                # 1. 显式指定碰牌：c=pon:5z>2p / c=碰5z>2p / c=pon5z>2p / c=pon:8m>2p
                # 2. 简写：c=pon>2p（自动推断手牌唯一对子；若存在多个对子则提示必须指明）
                fu_tile = None
                call_part = part
                if ">" in part:
                    main_p, fu_p = part.split(">", 1)
                    call_part = main_p.strip()
                    fu_norm = normalize_tile_text(fu_p.strip())
                    if len(fu_norm) != 2:
                        return None, f"碰牌后切牌格式错误：{fu_p}"
                    fu_tile = fu_norm

                # 提取碰的目标牌
                pon_target = None
                m_t = re.search(r'(?i)(?:pon|碰)[:：]?([0-9mpsz]{2})', call_part)
                if m_t:
                    pon_target = normalize_tile_text(m_t.group(1))

                # 若未显式写碰哪张牌，分析手牌中现存的所有对子/暗刻
                if not pon_target:
                    from collections import Counter
                    hand_counts = Counter(hand_tiles)
                    pairs = [t for t, count in hand_counts.items() if count >= 2]
                    if len(pairs) == 1:
                        pon_target = pairs[0]
                    elif len(pairs) > 1:
                        p_str = ", ".join(pairs)
                        return None, (
                            f"无法确定碰哪张牌：你的手牌中存在多个对子 [{p_str}]。\n"
                            f"💡 请在副露中明确指出碰哪张牌，例如：c=pon:{pairs[0]}>{fu_tile or '2p'} 或 c=碰{pairs[0]}>{fu_tile or '2p'}"
                        )
                    else:
                        return None, f"副露错误：手牌中没有可以碰的对子（手牌：{''.join(hand_tiles)}）"

                cand_dict = {
                    "tile": "pon",
                    "riichi": False,
                    "kan": False,
                    "kyushu": False,
                    "pon": True,
                    "call_tile": pon_target,
                    "follow_up_discard": fu_tile,
                    "candidate": f"pon:{pon_target}>{fu_tile}" if fu_tile else f"pon:{pon_target}",
                }
                candidates.append(cand_dict)
                continue
            if part in ("daiminkan", "minkan", "大明杠", "明杠"):
                # 大明杠不模拟：杠后需岭上摸牌并再打一张，无法替用户假造这条支路，
                # 因此明确拒绝，而不是生成不可信的期望。
                return None, (
                    "大明杠暂不模拟：杠后需要岭上摸牌并再打一张，无法替你假造这条支路。"
                    "请改为比较 吃/碰/跳过（或碰后打牌）等候选。"
                )

            is_riichi = False
            is_kan = False
            clean_part = part.lower().strip()
            if clean_part.startswith("riichi:") or clean_part.startswith("立直:"):
                is_riichi = True
                clean_part = clean_part.split(":", 1)[1].strip()
            elif clean_part.startswith("riichi") or clean_part.startswith("立直"):
                is_riichi = True
                clean_part = re.sub(r'^(?:riichi|立直)\s*', '', clean_part).strip()
            elif clean_part.startswith("r") and len(clean_part) == 3:
                is_riichi = True
                clean_part = clean_part[1:]
            elif clean_part.endswith("r"):
                is_riichi = True
                clean_part = clean_part[:-1]
            elif clean_part.endswith("k") or clean_part.endswith("杠"):
                is_kan = True
                clean_part = clean_part[:-1].rstrip("杠")
            tile = normalize_tile_text(clean_part)
            if len(tile) != 2:
                return None, f"候选格式错误：{part}"
            # 严格规则校验 2: 切牌候选必须是手牌中实际存在的牌 (赤五与普通五严格区分)
            tile_in_hand = False
            if tile in ("0m", "0p", "0s"):
                tile_in_hand = tile in hand_tiles
            elif tile in ("5m", "5p", "5s"):
                tile_in_hand = tile in hand_tiles
            else:
                tile_in_hand = any(normalize_tile_text(t) == tile for t in hand_tiles)

            if not tile_in_hand and not is_kan:
                return None, f"切牌动作违背规则：候选牌【{tile}】不在自家手牌中（当前手牌：{''.join(hand_tiles)}）"

            if is_kan:
                if hand_tiles.count(tile) < 4:
                    return None, f"暗杠候选 {tile}k 不合法：手牌中 {tile} 只有 {hand_tiles.count(tile)} 张（需要 4 张）。"
                candidates.append({"tile": tile, "riichi": False, "kan": True, "candidate": f"kan:{tile}"})
            else:
                c_name = f"riichi:{tile}" if is_riichi else tile
                candidates.append({"tile": tile, "riichi": is_riichi, "kan": False, "candidate": c_name})

    if not candidates:
        return None, "没有识别到候选。"

    # 严格规则校验 3: 副露判断只能在 3n+1（未摸牌，等待响应）输入，
    # 切牌判断只能在 3n+2（已摸牌，等待打牌）输入。禁止 13 张走打牌路径。
    n_hand = len(hand_tiles)
    is_response = any(c.get("chi") or c.get("pon") or c.get("pass") or c.get("ron") or c.get("daiminkan") for c in candidates)
    if is_response and n_hand % 3 != 1:
        return None, (
            f"副露(吃/碰/大明杠/和牌/见逃)判断的手牌必须是 3n+1 张（未摸牌状态，如 13 张），"
            f"当前 {n_hand} 张属于 3n+2 张（已摸牌状态），请改用打牌判断或去掉一张手牌。"
        )
    if not is_response and n_hand % 3 != 2:
        return None, (
            f"打牌判断的手牌必须是 3n+2 张（摸牌后状态，如 14 张），"
            f"当前 {n_hand} 张属于 3n+1 张（未摸牌状态）。"
            f"若要做副露判断，请在候选里写 c=chi:3m / pon:3m / pass 等响应动作。"
        )

    target_past = None
    opp_rivers = None
    prefix_melds = []
    call_tile = None
    for cand in candidates:
        if cand.get("call_tile"):
            call_tile = cand["call_tile"]
            break

    # CLI seat=东南西北 names CURRENT seat winds, not initial player IDs.
    # Generate in wind coordinates (East is always dealer); rotate exactly once
    # at the API boundary below.
    effective_oya = 0
    round_oya = (int(round_raw[1]) - 1) % 4

    # Structural validation is shared with the service, including when the bot
    # package is imported standalone from outside the repository cwd.
    import sys
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[2])
    if root not in sys.path:
        sys.path.insert(0, root)

    parsed_target_past = None
    parsed_opp_rivers = None
    if river_raw:
        try:
            parsed_target_past, parsed_opp_rivers, prefix_melds, river_err = _parse_river_spec(
                river_raw, effective_target_seat, x_val, effective_oya, strict=is_response,
            )
        except ValueError as exc:
            return None, str(exc)
        if river_err:
            return None, river_err

    if is_response:
        if x_val == 1 and effective_target_seat == 0:
            return None, "东家(庄家)第1巡尚无上家弃牌，不能吃/碰/过；请使用真实响应时点（如 x=2）"
        # All candidates describe ONE latest discard, not an invented discard
        # at the end of the caller's nominal turn. Chi is restricted to kamicha;
        # pon/pass/ron may respond before the other opponents take that turn.
        possible = None
        for c in candidates:
            choices = None
            if c.get("call_tile"):
                choices = {c["call_tile"]}
            elif c.get("chi"):
                choices = {f"{n}{s}" for s in "mps" for n in range(1, 10)
                           if c["chi"] in _infer_chi_consumed(c["chi"], f"{n}{s}")}
            if choices is not None:
                possible = choices if possible is None else possible & choices
        if river_raw:
            from mortal_app.call_context import latest_response_discard
            explicit_rivers = [list(row) for row in parsed_opp_rivers or [[], [], [], []]]
            explicit_rivers[effective_target_seat] = parsed_target_past or []
            try:
                actor, latest_tile = latest_response_discard(explicit_rivers, 0, effective_target_seat, x_val)
            except ValueError as exc:
                return None, str(exc)
            if any(c.get("chi") for c in candidates) and actor != (effective_target_seat + 3) % 4:
                return None, "吃牌只能响应上家的最新弃牌；碰牌可响应任意对手"
            latest = {latest_tile}
            possible = latest if possible is None else possible & latest
        if not possible:
            return None, "副露候选与牌河必须指向同一张最新弃牌；请明确目标牌"
        if len(possible) != 1:
            return None, "吃牌搭子对应多个目标，请写 chi:23m(4m) 或提供最新弃牌"
        call_tile = next(iter(possible))
        for c in candidates:
            if c.get("chi") or c.get("pon") or c.get("daiminkan"):
                c["call_tile"] = call_tile

    if river_raw:
        if is_response:
            # A specified response river is evidence, not a template to pad
            # with later invented discards. Exact clock/tiles are rechecked at
            # the service boundary by response_context.
            target_past, opp_rivers = parsed_target_past, parsed_opp_rivers
        else:
            target_past, opp_rivers = _generate_default_rivers(
                hand_tiles,
                effective_target_seat,
                effective_oya,
                x_val,
                call_target_tile=call_tile,
                partial_target_past=parsed_target_past,
                partial_opp_rivers=parsed_opp_rivers,
            )
    elif x_val >= 2 or (x_val >= 1 and effective_target_seat != 0):
        target_past, opp_rivers = _generate_default_rivers(
            hand_tiles,
            effective_target_seat,
            effective_oya,
            x_val,
            call_target_tile=call_tile,
        )

    request: dict[str, Any] = {
        "model_id": model_id_val,
        "hand": hand_norm,
        "dora": dora_indicator,
        "discards": candidates,
        "round": round_raw,
        "honba": int(honba_raw),
        "kyotaku": int(kyotaku_val),
        "runs": runs_raw,
        "target_seat": target_seat_val,
        "x": x_val,
        "target_past_discards": target_past if target_past else None,
        "opponent_rivers": opp_rivers,
        "prefix_melds": prefix_melds if prefix_melds else None,
        "tau": tau_val,
        "weighted": opp_rivers is not None,
    }

    if scores_val:
        request["scores"] = scores_val

    # 内部键：无 c= 候选时模型推断顺带产出的 Q/P。仅 bot 侧消费（报表归一P），
    # bot.execute 在 create_run 之前 pop 掉，绝不外发到后端。
    if precomputed_qp is not None:
        request["_model_qp"] = precomputed_qp

    if target_past is not None and x_val >= 1:
        tp_len = len(target_past)
        if tp_len not in (max(0, x_val - 1), x_val):
            seat_names = ['东', '南', '西', '北']
            s_name = seat_names[effective_target_seat]
            return None, (
                f'牌河张数错误：你设定了【{s_name}家 第 {x_val} 巡】，'
                f'自家历史舍牌应为 {max(0, x_val - 1)} 张（摸牌决策）或 {x_val} 张（切牌后反应决策），'
                f'当前输入了 {tp_len} 张。'
            )
    # Absolute engine seats: round dealer + current seat wind. Rivers, hand,
    # scores and model evaluation must agree on this single conversion.
    request["target_seat"] = (round_oya + effective_target_seat) % 4
    if opp_rivers is not None:
        absolute_rivers = [[], [], [], []]
        for wind, river in enumerate(opp_rivers):
            absolute_rivers[(round_oya + wind) % 4] = river
        request["opponent_rivers"] = absolute_rivers
    for meld in prefix_melds:
        for key in ("actor", "target"):
            if meld.get(key) is not None:
                meld[key] = (round_oya + meld[key]) % 4

    # Repeat at the service boundary: a direct API request must obey the same
    # clock and physical constraints, independent of the bot parser.
    from mortal_app.call_context import response_context
    try:
        response_context(request)
    except ValueError as exc:
        return None, str(exc)
    return request, None


def parse_message(raw_msg: str) -> tuple[dict[str, Any] | None, str | None]:
    """Compatibility alias for bot message dispatch."""
    return parse_sim_command(raw_msg)
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
    """将各种手牌写法归一化为标准的 compact 格式（如 '123m456p789s11222z'）。"""
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

    explicit = re.findall(r"[0-9][mpszMPSZ]|[东南西北白发發中]", t)
    if explicit:
        out = []
        for item in explicit:
            if item in HONOR_MAP:
                out.append(HONOR_MAP[item])
            else:
                out.append(item.lower())
        return "".join(out)

    return t


def _kyushu_kinds(tiles: list[str]) -> int:
    yaojiu = {"1m", "9m", "1p", "9p", "1s", "9s", "1z", "2z", "3z", "4z", "5z", "6z", "7z"}
    return len(set(tiles) & yaojiu)


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


def _parse_river_tokens_string(discards_raw: str) -> list[tuple[str, bool, bool, dict[str, Any] | None]]:
    """Parse comma/space/compact separated tile tokens."""
    discards_raw = discards_raw.strip()
    if not discards_raw:
        return []
    if any(sep in discards_raw for sep in (",", "，", "、", " ", "  ")):
        raw_tokens = [d.strip() for d in re.split(r'[,，、\s]+', discards_raw) if d.strip()]
    else:
        raw_tokens = re.findall(r'[0-9][mpsz][tT\^摸rR立]{0,2}|[1-7]z[tT\^摸rR立]{0,2}|[东南西北白发中][tT\^摸rR立]{0,2}', discards_raw)

    out = []
    for tok in raw_tokens:
        parsed = _parse_river_token(tok)
        if parsed:
            out.append(parsed)
    return out


def _parse_river_spec(river_raw: str, target_seat: int, x: int = 1, oya: int = 0) -> tuple[list[tuple[str, bool, bool]], list[list[tuple[str, bool, bool]]] | None, list[dict[str, Any]], str | None]:
    opponent_rivers: list[list[tuple[str, bool, bool]]] = [[], [], [], []]
    target_past: list[tuple[str, bool, bool]] = []
    melds: list[dict[str, Any]] = []
    river_raw = river_raw.strip()

    slash_sections = [s.strip() for s in re.split(r'[/|／｜]+', river_raw) if s.strip()]
    if not any(":" in s or "：" in s or "=" in s for s in slash_sections):
        if len(slash_sections) == 4:
            for seat_idx, sec in enumerate(slash_sections):
                tokens = _parse_river_tokens_string(sec)
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
        else:
            prec_seats = []
            cur = oya
            while cur != target_seat:
                prec_seats.append(cur)
                cur = (cur + 1) % 4
            if len(slash_sections) == len(prec_seats):
                for idx, seat_idx in enumerate(prec_seats):
                    tokens = _parse_river_tokens_string(slash_sections[idx])
                    for tok in tokens:
                        tile_s, ts, is_r, m_info = tok
                        if m_info:
                            m_info["target"] = seat_idx
                            m_info["pai"] = tile_s
                            melds.append(m_info)
                        opponent_rivers[seat_idx].append((tile_s, ts, is_r))
                has_opp = any(len(r) > 0 for i, r in enumerate(opponent_rivers) if i != target_seat)
                return target_past, opponent_rivers if has_opp else None, melds, None
            return [], None, [], f"牌河分段数量 ({len(slash_sections)}) 与前置出牌玩家数 ({len(prec_seats)}) 或四家总数 (4) 不符"

    sections = [s.strip() for s in re.split(r'[;；/|／｜\s]+', river_raw) if s.strip()]
    for sec in sections:
        if ":" not in sec and "：" not in sec and "=" not in sec:
            continue
        parts = re.split(r'[:：=]', sec, maxsplit=1)
        if len(parts) != 2:
            continue
        seat_token = parts[0].strip().lower()
        if seat_token not in SEAT_MAP:
            return [], None, [], f"未知座位编号 '{parts[0]}'，支持 0-3 / E,S,W,N / 东南西北"
        seat_idx = SEAT_MAP[seat_token]
        tokens = _parse_river_tokens_string(parts[1])
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



def _generate_default_rivers(
    hand_tiles: list[str],
    target_seat: int,
    oya: int,
    x: int,
) -> tuple[list[tuple[str, bool, bool]], list[list[tuple[str, bool, bool]]]]:
    """当巡目 x >= 2 且用户未提供牌河时，自动生成四家物理合法、无冲突且符合牌理的牌河：
       1. 严格按 字牌 -> 幺九 -> 28 -> 37 -> 456 优先级出牌；
       2. 严禁打出手牌以及手牌附近的牌（±1 邻张/进张/搭子）；
       3. 首巡四家各打不同牌，绝对避免触发四风连打中途流局。
    """
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

    def pick_tile_for_player(p_idx: int, turn_idx: int, used_this_turn: set[str]) -> str:
        # 首选：从未在当巡出现过的 allowed_pool 中挑选
        for t in allowed_pool:
            if t not in used_this_turn and tile_used_counts.get(t, 0) < 4:
                tile_used_counts[t] = tile_used_counts.get(t, 0) + 1
                used_this_turn.add(t)
                return t
        for t in allowed_pool:
            if tile_used_counts.get(t, 0) < 4:
                tile_used_counts[t] = tile_used_counts.get(t, 0) + 1
                used_this_turn.add(t)
                return t
        for t in TILES_BY_PRIORITY:
            if t not in hand_tiles and tile_used_counts.get(t, 0) < 4:
                tile_used_counts[t] = tile_used_counts.get(t, 0) + 1
                used_this_turn.add(t)
                return t
        return "1z"

    pos_target = (target_seat + 4 - oya) % 4
    rivers: list[list[tuple[str, bool, bool]]] = [[], [], [], []]

    for r in range(1, x + 1):
        used_this_turn: set[str] = set()
        for offset in range(4):
            p = (oya + offset) % 4
            pos_p = offset
            if r == x and pos_p == pos_target:
                break
            if r == x and pos_p > pos_target:
                continue
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

    # 0a. 提取巡目 x (支持 1..18)
    x_val = 1
    x_m = re.search(r"(?i)(?:^|(?<=[\s,;]))x[:：=]?(\d{1,2})\b", rest)
    if x_m:
        x_val = int(x_m.group(1))
        rest = rest[:x_m.start()] + " " + rest[x_m.end():]

    # 0b. 提取自身座位 seat
    target_seat_val = None
    seat_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:seat|座位)[:：=]?([0-3]|east|south|west|north|[eswn东南西北])\b", rest)
    if seat_m:
        s_tok = seat_m.group(1).lower()
        if s_tok in SEAT_MAP:
            target_seat_val = SEAT_MAP[s_tok]
        rest = rest[:seat_m.start()] + " " + rest[seat_m.end():]

    # 0c. 提取温度 tau
    tau_val = 1.0
    tau_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:tau|温度)[:：=]?(\d+(?:\.\d+)?)\b", rest)
    if tau_m:
        tau_val = float(tau_m.group(1))
        rest = rest[:tau_m.start()] + " " + rest[tau_m.end():]

    # 0d. 提取牌河 river
    river_raw = None
    river_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:river|河|牌河)[:：=]?([0-9mpszzt\^rR立\(（\)）\u4e00-\u9fa5,，:：;；/|／｜\s\-_东南西北ESWN]+?)(?=\s+[pPdDcCeEwWsS]|\s*$)", rest)
    if river_m:
        river_raw = river_m.group(1).strip()
        rest = rest[:river_m.start()] + " " + rest[river_m.end():]

    # 1. 提取点数 P...
    scores_raw = None
    scores_m = re.search(r'(?i)\b[pP][:：\s]?([-0-9,\s]+?)(?=\s+[cdCD\d]|\s*$)', rest)
    if scores_m:
        scores_raw = scores_m.group(1).strip()
        rest = rest[:scores_m.start()] + " " + rest[scores_m.end():]

    # 2. 提取宝牌 d...
    dora_m = re.search(r'(?i)\b[dD][:：\s]?([0-9mpsz]{2,4})\b', rest)
    if not dora_m:
        return None, "缺少宝牌参数，例：d8p 或 d4m"
    dora_raw = dora_m.group(1).strip()
    rest = rest[:dora_m.start()] + " " + rest[dora_m.end():]

    # 3. 提取候选 c... (若未提供，后续自动从手牌提取切牌候选)
    cand_m = re.search(r'(?i)(?:^|(?<=[\s,;]))[cC][:：=]?([a-zA-Z0-9mpszkrKR>:\-_,，、\s\u4e00-\u9fa5]+?)(?=\s+[pPdDeEwWsSxX]|\s*$)', rest)
    cand_raw = None
    if cand_m:
        cand_raw = cand_m.group(1).strip()
        rest = rest[:cand_m.start()] + " " + rest[cand_m.end():]

    # 4. 提取局与本场
    round_raw = "E1"
    honba_raw = "0"
    round_m = re.search(r'(?i)\b([EWSews][1-4])(?:-(\d+))?\b', rest)
    if round_m:
        round_raw = round_m.group(1).upper()
        honba_raw = round_m.group(2) or "0"
        rest = rest[:round_m.start()] + " " + rest[round_m.end():]

    # 5. 提取模拟局数
    runs_raw = 500
    runs_m = re.search(r'\b(\d{2,6})\b', rest)
    if runs_m:
        runs_raw = int(runs_m.group(1))
        rest = rest[:runs_m.start()] + " " + rest[runs_m.end():]

    # 6. 主手牌
    hand_raw = rest.strip()
    if not hand_raw:
        return None, "未找到手牌内容，请输入 13 或 14 张手牌。"

    hand_norm = normalize_tile_text(hand_raw)
    hand_tiles = [hand_norm[i:i+2] for i in range(0, len(hand_norm), 2)]
    if len(hand_tiles) not in (1, 2, 4, 5, 7, 8, 10, 11, 13, 14):
        return None, f"手牌张数不合法（必须为 3n+1 或 3n+2 张），当前识别 {len(hand_tiles)} 张：{hand_norm or '(未识别)'}"

    dora_norm = normalize_tile_text(dora_raw)
    if len(dora_norm) != 2:
        return None, f"宝牌格式错误：{dora_raw}，应为 1 张牌（如 d8p、d4m、d5z）。"
    # 用户输入 d<宝牌>，将其转换为对应的宝牌指示牌 (dora_marker)
    dora_indicator = dora_to_indicator(dora_norm)

    candidates = []
    if cand_raw is None:
        unique_hand = list(dict.fromkeys(hand_tiles))
        for tile in unique_hand[:4]:
            candidates.append({"tile": tile, "riichi": False, "kan": False})
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
            if part.startswith("chi:") or part.startswith("吃:"):
                sub = part.split(":", 1)[1].strip()
                fu_tile = None
                if ">" in sub:
                    c_part, fu_part = sub.split(">", 1)
                    fu_norm = normalize_tile_text(fu_part)
                    if len(fu_norm) == 2:
                        fu_tile = fu_norm
                    sub = c_part.strip()
                consumed_norm = normalize_tile_text(sub)
                c_tiles = [consumed_norm[i:i+2] for i in range(0, len(consumed_norm), 2)]
                if len(c_tiles) != 2:
                    return None, f"吃牌候选格式错误：{part}，例：chi:45m>6p 或 chi:4m5m"
                candidates.append({"tile": "chi", "riichi": False, "kan": False, "kyushu": False, "chi": c_tiles, "follow_up_discard": fu_tile})
                continue
            if part.startswith("pon") or part.startswith("碰"):
                fu_tile = None
                if ">" in part:
                    fu_part = part.split(">", 1)[1].strip()
                    fu_norm = normalize_tile_text(fu_part)
                    if len(fu_norm) == 2:
                        fu_tile = fu_norm
                candidates.append({"tile": "pon", "riichi": False, "kan": False, "kyushu": False, "pon": True, "follow_up_discard": fu_tile})
                continue
            if part in ("daiminkan", "minkan", "大明杠", "明杠"):
                candidates.append({"tile": "daiminkan", "riichi": False, "kan": False, "kyushu": False, "daiminkan": True})
                continue

            kan = part.endswith("k")
            riichi = part.endswith("r")
            if kan:
                part = part[:-1]
            elif riichi:
                part = part[:-1]
            tile = normalize_tile_text(part)
            if len(tile) != 2:
                return None, f"候选格式错误：{part}"
            if kan:
                if hand_tiles.count(tile) < 4:
                    return None, f"暗杠候选 {tile}k 不合法：手牌中 {tile} 只有 {hand_tiles.count(tile)} 张（需要 4 张）。"
                candidates.append({"tile": tile, "riichi": False, "kan": True})
            else:
                candidates.append({"tile": tile, "riichi": riichi, "kan": False})

    if not candidates:
        return None, "没有识别到候选。"

    effective_target_seat = target_seat_val if target_seat_val is not None else 0
    target_past = None
    opp_rivers = None
    prefix_melds = []
    if river_raw:
        target_past, opp_rivers, prefix_melds, river_err = _parse_river_spec(river_raw, effective_target_seat, x_val, 0)
        if river_err:
            return None, river_err
    elif x_val >= 2:
        # 当巡目 x >= 2 且用户未提供牌河时，自动生成四家合法默认牌河
        target_past, opp_rivers = _generate_default_rivers(hand_tiles, effective_target_seat, 0, x_val)

    request: dict[str, Any] = {
        "hand": hand_norm,
        "dora": dora_indicator,
        "discards": candidates,
        "round": round_raw,
        "honba": int(honba_raw),
        "kyotaku": 0,
        "runs": runs_raw,
        "target_seat": target_seat_val,
        "x": x_val,
        "target_past_discards": target_past if target_past else None,
        "opponent_rivers": opp_rivers,
        "prefix_melds": prefix_melds if prefix_melds else None,
        "tau": tau_val,
        "weighted": opp_rivers is not None,
    }

    if scores_raw:
        scores_parts = [s.strip() for s in re.split(r'[,，\s]+', scores_raw) if s.strip()]
        if len(scores_parts) == 4:
            try:
                parsed_scores = []
                for p in scores_parts:
                    val = int(p)
                    if abs(val) < 1000:
                        val *= 100
                    parsed_scores.append(val)
                target_p = target_seat_val if target_seat_val is not None else 0
                rel_self = parsed_scores[target_p]
                rel_shimo = parsed_scores[(target_p + 1) % 4]
                rel_toimen = parsed_scores[(target_p + 2) % 4]
                rel_kami = parsed_scores[(target_p + 3) % 4]
                request["scores"] = {"self": rel_self, "shimocha": rel_shimo, "toimen": rel_toimen}
            except ValueError:
                return None, f"点数格式错误：{scores_raw}"

    return request, None


def parse_message(raw_msg: str) -> tuple[dict[str, Any] | None, str | None]:
    """Compatibility alias for bot message dispatch."""
    return parse_sim_command(raw_msg)

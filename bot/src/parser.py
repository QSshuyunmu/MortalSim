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

        for sec in sections:
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

    # 2. 无命名分段：按斜杠 '/' 分隔
    slash_sections = [s.strip() for s in re.split(r'[/|／｜]+', river_raw) if s.strip()]
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
    elif len(slash_sections) < 4:
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



# 基于天凤真实高段位牌谱统计拟合的各巡舍牌类别概率与摸切率分布
REAL_RIVER_PROBS = {
    1: {"wind": 0.466, "dragon": 0.126, "19": 0.334, "28": 0.042, "456": 0.032, "tsumo_rate": 0.073},
    2: {"wind": 0.320, "dragon": 0.211, "19": 0.290, "28": 0.099, "456": 0.080, "tsumo_rate": 0.154},
    3: {"wind": 0.209, "dragon": 0.230, "19": 0.263, "28": 0.151, "456": 0.147, "tsumo_rate": 0.226},
    4: {"wind": 0.164, "dragon": 0.185, "19": 0.247, "28": 0.196, "456": 0.208, "tsumo_rate": 0.313},
    5: {"wind": 0.141, "dragon": 0.138, "19": 0.231, "28": 0.196, "456": 0.294, "tsumo_rate": 0.329},
    6: {"wind": 0.140, "dragon": 0.100, "19": 0.219, "28": 0.211, "456": 0.330, "tsumo_rate": 0.408},
}

def _generate_default_rivers(
    hand_tiles: list[str],
    target_seat: int,
    oya: int,
    x: int,
    call_target_tile: str | None = None,
    call_from_seat: int | None = None,
    partial_target_past: list[tuple[str, bool, bool]] | None = None,
    partial_opp_rivers: list[list[tuple[str, bool, bool]]] | None = None,
    dora_indicator: str | None = None,
) -> tuple[list[tuple[str, bool, bool]], list[list[tuple[str, bool, bool]]]]:
    """拟合天凤真实牌谱统计的高自然度牌河补齐引擎：
       1. 严格避开手牌及其附近搭子进张牌（±1 邻张/搭子）；
       2. 牌池分类（客风/场风、三元牌、幺九、28、456中张）严格按照巡目概率轮盘抽样；
       3. 拟合真实手摸切比率（t 摸切标识随巡目自然上升）；
       4. 严格全局扣减固定牌张预算（自家14张、宝牌指示牌、所有已打出牌），绝不超 4 枚；
       5. 完美适配副露跨圈断点：支持指定供牌方 call_from_seat，时序精准截断。
    """
    import random
    forbidden = set()
    for t in hand_tiles:
        norm_t = "5m" if t in ("0m", "5mr") else ("5p" if t in ("0p", "5pr") else ("5s" if t in ("0s", "5sr") else t))
        forbidden.add(norm_t)
        if norm_t.endswith("z"):
            continue
        suit = norm_t[-1]
        num = int(norm_t[0])
        if num > 1:
            forbidden.add(f"{num-1}{suit}")
        if num < 9:
            forbidden.add(f"{num+1}{suit}")

    # 统计全场已占用的牌张预算
    tile_used_counts: dict[str, int] = {}
    for t in hand_tiles:
        norm_t = "5m" if t in ("0m", "5mr") else ("5p" if t in ("0p", "5pr") else ("5s" if t in ("0s", "5sr") else t))
        tile_used_counts[norm_t] = tile_used_counts.get(norm_t, 0) + 1
    if dora_indicator:
        norm_d = "5m" if dora_indicator in ("0m", "5mr") else ("5p" if dora_indicator in ("0p", "5pr") else ("5s" if dora_indicator in ("0s", "5sr") else dora_indicator))
        tile_used_counts[norm_d] = tile_used_counts.get(norm_d, 0) + 1

    rivers: list[list[tuple[str, bool, bool]]] = [[], [], [], []]
    if partial_target_past:
        rivers[target_seat] = list(partial_target_past)
    if partial_opp_rivers:
        for p in range(4):
            if p != target_seat and p < len(partial_opp_rivers):
                rivers[p] = list(partial_opp_rivers[p] or [])

    # 将用户已显式指定的舍牌计入消耗
    for p in range(4):
        for item in rivers[p]:
            t = item[0]
            norm_t = "5m" if t in ("0m", "5mr") else ("5p" if t in ("0p", "5pr") else ("5s" if t in ("0s", "5sr") else t))
            tile_used_counts[norm_t] = tile_used_counts.get(norm_t, 0) + 1

    # 构造各分类候选池
    CATEGORIES = {
        "wind": ["1z", "2z", "3z", "4z"],
        "dragon": ["5z", "6z", "7z"],
        "19": ["1m", "9m", "1p", "9p", "1s", "9s"],
        "28": ["2m", "8m", "2p", "8p", "2s", "8s"],
        "456": ["3m", "4m", "5m", "6m", "7m", "3p", "4p", "5p", "6p", "7p", "3s", "4s", "5s", "6s", "7s"],
    }

    # 确定前驱出牌者
    if call_from_seat is not None:
        actual_from_seat = call_from_seat
    else:
        actual_from_seat = (target_seat + 3) % 4

    def pick_realistic_tile(p: int, r: int, used_this_turn: set[str], last_tile: str | None) -> tuple[str, bool]:
        probs = REAL_RIVER_PROBS.get(r, REAL_RIVER_PROBS[6])
        tsumo_rate = probs["tsumo_rate"]
        is_tsumo = (random.random() < tsumo_rate) if r > 1 else False

        cat_weights = [
            ("wind", probs["wind"]),
            ("dragon", probs["dragon"]),
            ("19", probs["19"]),
            ("28", probs["28"]),
            ("456", probs["456"]),
        ]
        shuffled_cats = sorted(cat_weights, key=lambda x: x[1] * random.random(), reverse=True)

        for cat_name, _ in shuffled_cats:
            cands = [t for t in CATEGORIES[cat_name] if t not in forbidden and t not in used_this_turn and tile_used_counts.get(t, 0) < 4 and t != last_tile]
            if cands:
                chosen = random.choice(cands)
                tile_used_counts[chosen] = tile_used_counts.get(chosen, 0) + 1
                used_this_turn.add(chosen)
                return chosen, is_tsumo

        # 兜底：全牌山寻找未超限且不在本巡同名出现的牌
        all_tiles = [f"{n}{s}" for s in ("m", "p", "s") for n in range(1, 10)] + [f"{n}z" for n in range(1, 8)]
        valid_fallbacks = [t for t in all_tiles if t not in forbidden and tile_used_counts.get(t, 0) < 4 and t != last_tile]
        if valid_fallbacks:
            chosen = random.choice(valid_fallbacks)
            tile_used_counts[chosen] = tile_used_counts.get(chosen, 0) + 1
            used_this_turn.add(chosen)
            return chosen, is_tsumo

        # 极端兜底
        for t in all_tiles:
            if tile_used_counts.get(t, 0) < 4:
                tile_used_counts[t] = tile_used_counts.get(t, 0) + 1
                used_this_turn.add(t)
                return t, is_tsumo
        return "1z", False

    # 循环遍历巡目 1..x
    for r in range(1, x + 1):
        used_this_turn: set[str] = set()
        for offset in range(4):
            p = (oya + offset) % 4

            # 时序断点判定
            if r == x:
                if call_target_tile:
                    # 如果有副露目标牌，当到达供牌者切牌时，供牌者打出后立即触发副露，后续玩家该巡不再摸打
                    pos_p = (p + 4 - oya) % 4
                    pos_from = (actual_from_seat + 4 - oya) % 4
                    if pos_p > pos_from:
                        continue
                else:
                    pos_p = (p + 4 - oya) % 4
                    pos_target = (target_seat + 4 - oya) % 4
                    if pos_p >= pos_target:
                        continue

            if len(rivers[p]) >= r:
                t = rivers[p][r - 1][0]
                norm_t = "5m" if t in ("0m", "5mr") else ("5p" if t in ("0p", "5pr") else ("5s" if t in ("0s", "5sr") else t))
                used_this_turn.add(norm_t)
                continue

            last_tile = rivers[p][-1][0] if rivers[p] else None

            # 若是副露牌点
            if call_target_tile and r == x and p == actual_from_seat:
                t = call_target_tile
                tile_used_counts[t] = tile_used_counts.get(t, 0) + 1
                used_this_turn.add(t)
                is_tsumo = (random.random() < 0.25)
                rivers[p].append((t, is_tsumo, False))
            else:
                chosen_t, is_tsumo = pick_realistic_tile(p, r, used_this_turn, last_tile)
                rivers[p].append((chosen_t, is_tsumo, False))

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

    # 3. 提取温度 tau
    tau_val = 1.0
    tau_m = re.search(r"(?i)(?:^|(?<=[\s,;]))(?:tau|温度)[:：=]?(\d+(?:\.\d+)?)\b", rest)
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

    # 7. 提取候选 c... (支持 c=... 或 ctsumo,...)
    cand_m = re.search(r'(?i)(?:^|(?<=[\s,;]))[cC][:：=]?([a-zA-Z0-9mpszkrKR>:\-_,，、\[\]\(\)（）\u4e00-\u9fa5]+?)(?=\s+[pPdDeEwWsSxX]|\s+\d+\b|\s*$)', rest)
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
                # 支持：
                # 1. 显式指定碰牌：c=pon:5z>2p / c=碰5z>2p / c=pon5z>2p / c=pon:8m>2p
                # 2. 简写：c=pon>2p（自动推断手牌唯一对子；若存在多个对子则提示必须指明）
                fu_tile = None
                call_part = part
                if ">" in part:
                    main_p, fu_p = part.split(">", 1)
                    call_part = main_p.strip()
                    fu_norm = normalize_tile_text(fu_p.strip())
                    if len(fu_norm) == 2:
                        fu_tile = fu_norm

                # 提取碰的目标牌
                pon_target = None
                call_from_seat = None
                m_from = re.search(r'[\[\(（](东|南|西|北|0|1|2|3|[eswnESWN]|下家|对家|上家)[\]\)）]', call_part)
                if m_from:
                    from_tok = m_from.group(1).lower()
                    call_part = call_part[:m_from.start()] + call_part[m_from.end():]
                    if from_tok in ("下家", "shimocha"):
                        call_from_seat = (effective_target_seat + 1) % 4
                    elif from_tok in ("对家", "toimen"):
                        call_from_seat = (effective_target_seat + 2) % 4
                    elif from_tok in ("上家", "kamicha"):
                        call_from_seat = (effective_target_seat + 3) % 4
                    elif from_tok in SEAT_MAP:
                        call_from_seat = SEAT_MAP[from_tok]

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
                    "call_from_seat": call_from_seat,
                    "follow_up_discard": fu_tile,
                    "candidate": f"pon:{pon_target}>{fu_tile}" if fu_tile else f"pon:{pon_target}",
                }
                candidates.append(cand_dict)
                continue
            if part in ("daiminkan", "minkan", "大明杠", "明杠"):
                candidates.append({"tile": "daiminkan", "riichi": False, "kan": False, "kyushu": False, "daiminkan": True})
                continue

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

    target_past = None
    opp_rivers = None
    prefix_melds = []
    call_tile = None
    call_from = None
    for cand in candidates:
        if cand.get("call_tile"):
            call_tile = cand["call_tile"]
            call_from = cand.get("call_from_seat")
            break

    if river_raw:
        parsed_target_past, parsed_opp_rivers, prefix_melds, river_err = _parse_river_spec(river_raw, effective_target_seat, x_val, 0)
        if river_err:
            return None, river_err
        # 增量自动补齐其余未指定或张数不足的玩家牌河
        target_past, opp_rivers = _generate_default_rivers(
            hand_tiles,
            effective_target_seat,
            0,
            x_val,
            call_target_tile=call_tile,
            call_from_seat=call_from,
            partial_target_past=parsed_target_past,
            partial_opp_rivers=parsed_opp_rivers,
            dora_indicator=dora_indicator,
        )
    elif x_val >= 2 or (x_val >= 1 and effective_target_seat != 0):
        target_past, opp_rivers = _generate_default_rivers(
            hand_tiles,
            effective_target_seat,
            0,
            x_val,
            call_target_tile=call_tile,
            call_from_seat=call_from,
            dora_indicator=dora_indicator,
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
    return request, None


def parse_message(raw_msg: str) -> tuple[dict[str, Any] | None, str | None]:
    """Compatibility alias for bot message dispatch."""
    return parse_sim_command(raw_msg)
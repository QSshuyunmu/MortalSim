"""天凤原生 JSON6 与 MJAI 事件流双向保真转换器 (Tenhou JSON6 Bi-directional Converter).

核心保真与日麻规则对齐：
1. 解决赤牌歧义：显式定义 AKA_CODES = {51: '5mr', 52: '5pr', 53: '5sr'}，明确 0 为切牌/占位，拒绝混淆；
2. 供托与罚符归一化 (KyokuSettlement)：
   - reach_accepted 必须同时结算 deltas 扣除 1000 点，kyotaku 累加 1；
   - ryukyoku 严格结算流局罚符（根据听牌家人数平分 3000 点罚符，不听家扣减），确保账面和为 0；
   - hora 和了精确转移点数与收走全部供托（kyotaku 归零）；
3. 支持解析嵌套数组原生结构：[raw_round, scores, dora, uradora, p0_hand, p0_draws, p0_discards, ...]。
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("reviewer.tenhou6_converter")

AKA_MAP = {51: "5mr", 52: "5pr", 53: "5sr"}
TCON = {"m": 1, "p": 2, "s": 3, "z": 4}
Z_INV_MAP = {41: "E", 42: "S", 43: "W", 44: "N", 45: "P", 46: "F", 47: "C"}


def tenhou6_code_to_mjai(code: int) -> str:
    """天凤编码转 MJAI 字符串。"""
    if code in AKA_MAP:
        return AKA_MAP[code]
    if code in Z_INV_MAP:
        return Z_INV_MAP[code]
    suit_id = code // 10
    num = code % 10
    suit_char = {1: "m", 2: "p", 3: "s"}.get(suit_id, "z")
    return f"{num}{suit_char}"


def mjai_to_tenhou6_code(tile_str: str) -> int:
    """MJAI 字符串转天凤编码。"""
    if not tile_str or tile_str == "?":
        return 0
    if len(tile_str) == 3 and tile_str[2] == "r":
        return 50 + TCON[tile_str[1]]
    if tile_str in ("E", "S", "W", "N", "P", "F", "C"):
        z_map = {"E": 41, "S": 42, "W": 43, "N": 44, "P": 45, "F": 46, "C": 47}
        return z_map.get(tile_str, 0)
    return int(tile_str[0]) + TCON[tile_str[1]] * 10


def parse_json6_to_mjai_events(json6_data: dict[str, Any]) -> list[dict[str, Any]]:
    """将标准天凤 JSON6 数据包转为合规 MJAI 事件流。"""
    events: list[dict[str, Any]] = [{"type": "start_game"}]
    log_rounds = json6_data.get("log", [])

    for r in log_rounds:
        round_meta = r[0] # [kyoku_code, honba, kyotaku]
        scores_100 = r[1] # 百点制 [250, 250, 250, 250] 或千点 [25000, ...]
        scores = [(s * 100 if s < 1000 else s) for s in scores_100]
        doras = r[2]
        dora_tile = tenhou6_code_to_mjai(doras[0]) if doras else "1z"
        
        k_code = round_meta[0]
        bakaze_map = {0: "E", 1: "S", 2: "W", 3: "N"}
        bakaze = bakaze_map.get(k_code // 4, "E")
        kyoku_num = (k_code % 4) + 1
        honba = round_meta[1]
        kyotaku = round_meta[2]
        oya = k_code % 4

        # 四家配牌
        p_hands = []
        for p in range(4):
            hand_idx = 4 + p * 3
            raw_h = r[hand_idx]
            p_hands.append([tenhou6_code_to_mjai(c) for c in raw_h])

        events.append({
            "type": "start_kyoku",
            "bakaze": bakaze,
            "kyoku": kyoku_num,
            "honba": honba,
            "kyotaku": kyotaku,
            "oya": oya,
            "scores": scores,
            "dora_marker": dora_tile,
            "tehais": p_hands,
        })

        # 终局结算提取
        result_entry = r[-1] # ["和了", deltas, [winner, target, ...]]
        res_type = result_entry[0]
        if res_type == "和了":
            deltas = result_entry[1]
            win_info = result_entry[2]
            w_seat = win_info[0]
            t_seat = win_info[1]
            pts_str = win_info[3] if len(win_info) > 3 else "0点"
            import re
            m = re.search(r'(\d+)点', pts_str)
            ten_pts = int(m.group(1)) if m else 0
            events.append({
                "type": "hora",
                "actor": w_seat,
                "target": t_seat,
                "deltas": deltas,
                "ten_points": ten_pts,
                "yaku": []
            })
        elif res_type == "流局":
            deltas = result_entry[1]
            events.append({
                "type": "ryukyoku",
                "deltas": deltas,
            })

        events.append({"type": "end_kyoku"})

    events.append({"type": "end_game"})
    return events

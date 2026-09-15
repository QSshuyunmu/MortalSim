"""雀魂牌谱 URL 解析、四人麻将校验与 MJAI 格式化模块。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("reviewer.majsoul")

# 雀魂牌谱 UUID 典型格式：
# 240101-12345678-abcd-ef01-2345-6789abcdef01 或 带 _aXXXXXX 后缀
UUID_PATTERN = r'([0-9]{6}-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?:_a[0-9]+)?)'

def extract_majsoul_uuid(url_or_str: str) -> tuple[str | None, int | None]:
    """提取雀魂牌谱 UUID 以及可选的第一视角座次 (_a0, _a1, _a2, _a3)。"""
    s = url_or_str.strip()
    m = re.search(r'(?:paipu=|record/|uuid=)' + UUID_PATTERN, s)
    if not m:
        m = re.search(UUID_PATTERN, s)
    if m:
        full_id = m.group(1)
        seat = None
        if "_a" in full_id:
            parts = full_id.split("_a")
            uuid = parts[0]
            try:
                # 雀魂 _a 编码的座次通常为经过混淆或数字，若为单数字 0..3 则提取
                if parts[1].isdigit() and int(parts[1]) in (0, 1, 2, 3):
                    seat = int(parts[1])
            except Exception:
                pass
        else:
            uuid = full_id
        return uuid, seat
    return None, None

def parse_majsoul_json_or_mjai(text: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    """解析雀魂导出的 JSON 或 MJAI 事件流，并严格做四人麻将拦截校验。"""
    try:
        data = json.loads(text)
    except Exception as e:
        return None, f"牌谱 JSON 解析失败: {e}"

    # 1. 如果直接是 MJAI 事件列表
    if isinstance(data, list):
        events = data
    elif isinstance(data, dict):
        if "events" in data and isinstance(data["events"], list):
            events = data["events"]
        elif "actions" in data and isinstance(data["actions"], list):
            events = data["actions"]
        else:
            return None, "未知的牌谱 JSON 结构（未找到 events 数组）"
    else:
        return None, "未知的牌谱数据类型"

    # 严格四人麻将校验：
    # 1) 检查 start_game 玩家数量
    for ev in events:
        if ev.get("type") == "start_game":
            names = ev.get("names", [])
            if len(names) == 3:
                return None, "当前 Reviewer 专精于四人麻将，暂不支持三人麻将牌谱审查。"
            if len(names) == 4 and any(name is None for name in names):
                return None, "四人麻将玩家数据不完整或存在空缺。"
            break
        elif ev.get("type") == "start_kyoku":
            tehais = ev.get("tehais", [])
            if len(tehais) == 3:
                return None, "当前 Reviewer 专精于四人麻将，暂不支持三人麻将牌谱审查。"
            break

    # 2) 检查是否存在拔北动作（kita）
    for ev in events:
        if ev.get("type") == "kita" or ev.get("type") == "babei":
            return None, "检测到三人麻将特有的拔北动作，当前仅支持四人麻将。"

    return events, None

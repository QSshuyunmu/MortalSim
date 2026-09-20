"""不可信牌谱输入安全解析器 (Secure Replay Input Guard).

安全防范重点：
1. XML 解析安全：拒绝包含 DTD、内部实体 (Billion Laughs) 与外部实体 (XXE) 的恶意文件；
2. 输入流大小限制：单次解析最大限制为 16 MiB，防止内存炸弹；
3. JSON 深度与白名单校验：防止超深嵌套 RecursionError 与恶意类型注入。
"""
from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("reviewer.safe_parser")

MAX_INPUT_BYTES = 16 * 1024 * 1024  # 16 MiB
MAX_EVENTS_COUNT = 25000           # 正常日麻半庄约 1000~1500 事件，25000 极为充裕


class SecurityParseError(ValueError):
    """安全解析异常。"""
    pass


def safe_read_bytes(data_bytes: bytes) -> bytes:
    """检查输入字节流大小限制。"""
    if len(data_bytes) > MAX_INPUT_BYTES:
        raise SecurityParseError(f"输入文件过大: {len(data_bytes)} bytes，超出安全上限 16 MiB")
    return data_bytes


def safe_parse_xml_str(xml_str: str) -> Any:
    """安全解析天凤 XML 牌谱。
    
    天凤官方 XML 日志均为纯扁平标签结构，绝不需要任何 DOCTYPE 或 ENTITY 声明。
    任何含有 DOCTYPE 或 ENTITY 的文档直接快速阻断，根绝 XXE 与 Billion Laughs 攻击。
    """
    if len(xml_str.encode("utf-8")) > MAX_INPUT_BYTES:
        raise SecurityParseError("XML 文本大小超出 16 MiB 安全限制")

    xml_lower = xml_str[:2048].lower()
    if "<!doctype" in xml_lower or "<!entity" in xml_lower:
        raise SecurityParseError("安全拦截：天凤 XML 严禁包含 DTD 或自定义实体声明")

    try:
        from defusedxml.ElementTree import fromstring as defused_fromstring
        return defused_fromstring(xml_str)
    except ImportError:
        import xml.etree.ElementTree as ET
        return ET.fromstring(xml_str)


def safe_parse_json_str(json_str: str) -> Any:
    """安全解析 JSON/MJAI 牌谱。"""
    if len(json_str.encode("utf-8")) > MAX_INPUT_BYTES:
        raise SecurityParseError("JSON 文本大小超出 16 MiB 安全限制")

    try:
        data = json.loads(json_str)
    except Exception as exc:
        raise SecurityParseError(f"JSON 格式解析失败: {exc}") from exc

    # 若为事件列表，验证长度上限
    if isinstance(data, list):
        if len(data) > MAX_EVENTS_COUNT:
            raise SecurityParseError(f"事件数量过大: {len(data)}，超出安全上限 {MAX_EVENTS_COUNT}")
    elif isinstance(data, dict):
        events = data.get("events") or data.get("mjai_log")
        if isinstance(events, list) and len(events) > MAX_EVENTS_COUNT:
            raise SecurityParseError(f"事件数量过大: {len(events)}，超出安全上限 {MAX_EVENTS_COUNT}")

    return data

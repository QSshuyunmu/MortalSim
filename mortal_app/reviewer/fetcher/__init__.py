"""牌谱统一抓取、格式识别与四麻 MJAI 格式化主入口。"""
from __future__ import annotations

import logging
from typing import Any
from .tenhou import extract_tenhou_id, fetch_tenhou_xml, is_four_player_tenhou_xml
from .majsoul import extract_majsoul_uuid, parse_majsoul_json_or_mjai

log = logging.getLogger("reviewer.fetcher")

def load_replay_to_mjai(source_str: str) -> tuple[list[dict[str, Any]] | None, str | None, dict[str, Any]]:
    """统一加载天凤或雀魂牌谱输入，转换为 MJAI 事件列表。

    返回: (events, error_message, metadata)
    """
    metadata: dict[str, Any] = {"platform": "unknown", "id": "", "target_seat": 0}
    raw = source_str.strip()

    # 1. 尝试判定是否为天凤牌谱 (URL 或 Log ID)
    tenhou_id = extract_tenhou_id(raw)
    if tenhou_id:
        metadata["platform"] = "tenhou"
        metadata["id"] = tenhou_id
        try:
            xml_text = fetch_tenhou_xml(tenhou_id)
        except Exception as exc:
            return None, f"天凤牌谱下载失败 ({tenhou_id}): {exc}", metadata

        if not is_four_player_tenhou_xml(xml_text):
            return None, "当前 Reviewer 专精于四人麻将，暂不支持三人麻将牌谱审查。", metadata

        # 动态导入本地高效的 tenhou_to_mjai 转换器
        try:
            import sys
            from pathlib import Path
            p_str = str(Path("D:/tenhoulib").resolve())
            if p_str not in sys.path:
                sys.path.insert(0, p_str)
            from tenhou_to_mjai import convert_one
            import tempfile, os

            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False, mode="w", encoding="utf-8") as tf:
                tf.write(xml_text)
                tf_path = tf.name
            try:
                events = convert_one(tf_path)
            finally:
                if os.path.exists(tf_path):
                    os.unlink(tf_path)

            return events, None, metadata
        except Exception as exc:
            return None, f"天凤 XML 转 MJAI 失败: {exc}", metadata

    # 2. 尝试判定是否为雀魂牌谱 UUID 或链接
    majsoul_uuid, seat = extract_majsoul_uuid(raw)
    if majsoul_uuid:
        metadata["platform"] = "majsoul"
        metadata["id"] = majsoul_uuid
        if seat is not None:
            metadata["target_seat"] = seat

        # 雀魂在线只读网关尚未配置公共 token 时，提供明确的降级引导
        return None, (
            f"已识别雀魂牌谱 UUID: {majsoul_uuid}。\n"
            "目前雀魂官方网关需鉴权凭据，请直接将该对局导出的牌谱 .json 或 .mjai 文件发送给机器人进行极速审查！"
        ), metadata

    # 3. 尝试作为直接粘贴的 MJAI / JSON 文本解析
    if raw.startswith("[") or raw.startswith("{"):
        metadata["platform"] = "raw_json"
        events, err = parse_majsoul_json_or_mjai(raw)
        return events, err, metadata

    return None, "无法识别该牌谱输入，请输入天凤牌谱链接/ID，或直接发送导出的牌谱 JSON 文件。", metadata

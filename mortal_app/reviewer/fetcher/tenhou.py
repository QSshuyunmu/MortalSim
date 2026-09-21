"""天凤牌谱抓取与四人麻将校验模块。"""
from __future__ import annotations

import gzip
import logging
import re
import urllib.request
from typing import Any
import xml.etree.ElementTree as ET

log = logging.getLogger("reviewer.tenhou")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

def extract_tenhou_id(url_or_id: str) -> str | None:
    """从输入字符串提取天凤牌谱 log id。"""
    s = url_or_id.strip()
    m = re.search(r'(?:log=|\?)([0-9]{10}gm-[0-9a-f]{4}-[0-9a-f]{4,5}-[0-9a-f]{8})', s)
    if m:
        return m.group(1)
    m2 = re.search(r'\b([0-9]{10}gm-[0-9a-f]{4}-[0-9a-f]{4,5}-[0-9a-f]{8})\b', s)
    if m2:
        return m2.group(1)
    return None

def fetch_tenhou_xml(log_id: str, timeout: int = 15) -> str:
    """下载天凤牌谱原始 XML（绕过失效的系统本地代理环境变量，防止 10061）。"""
    url = f"https://tenhou.net/0/log/?{log_id}"
    req = urllib.request.Request(url, headers=HEADERS)
    # 强制直连天凤官网，不受未开启的本地 7890 代理影响
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read()
        try:
            return gzip.decompress(data).decode('utf-8', errors='ignore')
        except Exception:
            return data.decode('utf-8', errors='ignore')

def is_four_player_tenhou_xml(xml_text: str) -> bool:
    """校验天凤牌谱是否为四人麻将（坚决拦截三人麻将）。"""
    root = ET.fromstring(xml_text)
    go = root.find('.//GO')
    if go is not None:
        type_val = int(go.attrib.get('type', '0'))
        # 天凤 type 掩码：0x10 表示三人麻将 (sanma)
        if type_val & 0x10:
            return False
    un = root.find('.//UN')
    if un is not None:
        # 三人麻将四家名字中第四家通常为空或无 n3 属性
        n3 = un.attrib.get('n3')
        if not n3 or n3.strip() == "":
            return False
    return True

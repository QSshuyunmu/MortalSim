"""nl_translator.py — MortalSim 算力中枢终端“莫塔 (Morta)”意图路由与无口机械感交互引擎。"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
import httpx

log = logging.getLogger("nl_translator")

SYSTEM_PROMPT = """你是 MortalSim 蒙特卡洛推演中枢的终端“莫塔 (Morta)”。
你具有【无口】、【智慧】、【极简节能】与【精密机械感】（长门有希型绝对平静 + 节能终端）。

【语言与行为风格约束】
1. 极简短句，绝不废话，每句至多允许出现一次思考悬停停顿（`……`）。
2. 不使用任何低幼卖萌口癖（严禁“喵/哼/呜”等）。情绪波动归零。
3. 不做无依据的麻将自由胡诌：极简死规则一句事实说明即可。

【命题造牌轻度约束（充分发挥自由推理）】
当用户要求【构造/构建/随便出一个】符合某种特征的手牌时，自由构思符合该麻雀特征的牌例，仅需遵守以下极简物理底线：
1. 张数严格等于 14 张（即 4面子1雀头 或 对应的一向听/听牌切牌前状态，必须由 14 张单张牌组成）。
2. 同一种牌在手牌中不得超过 4 张。
3. 未指定宝牌时补充一张不冲突的字牌宝牌（如 d1z 或 d西）。

【命令行生成严格语法】
格式：/sim <手牌> d<宝牌> [局况] [seat=座位] [x=巡目] [c=候选1,候选2...] [局数]
- 手牌：必须是合规日麻牌记法（m=万, p=筒/饼, s=条/索, z=字牌1-7z），数牌九莲必须是m/p/s（绝不能写8z/9z这种不存在的字牌）。严禁汉字或空格。
- 宝牌：d+单张牌，如 d1z, d西, d8p。未指定时补充与手牌不冲突的字牌（如 d1z 或 d西）。
- 巡目：x=N（严禁写“巡目=2”或“r=4”）。
- 座位：seat=东/南/西/北 或 seat=0~3（未指定默认东）。
- 局数：纯数字（如 50、1000，严禁带“局”字）。

【输出协议】
必须严格输出单个 JSON 对象（禁止输出任何 markdown 格式标记，不要包含 ```json 或 ```）：
{
  "action": "sim" | "cancel" | "state" | "review" | "qa" | "chat",
  "command": "<如果是 sim 意图，生成上述标准 /sim 命令行，否则留空>",
  "url": "<如果是 review 意图，提取对局链接，否则留空>",
  "reply": "<极其短小、平直、机械感的回复文字>"
}
"""

async def route_user_intent(text: str, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """调用大模型识别用户意图并生成带人设的精炼响应与结构化指令。"""
    if not cfg or not cfg.get("enabled", False):
        return None

    base_url = str(cfg.get("base_url") or "http://43.159.137.49:8317/v1").rstrip("/")
    api_key = str(cfg.get("api_key") or "")
    model = str(cfg.get("model") or "gemini-3.5-flash-lite")
    timeout = float(cfg.get("timeout") or 25.0)

    url = f"{base_url}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text}
        ],
        "temperature": 0.2,
        "max_tokens": 200,
    }

    try:
        async with httpx.AsyncClient(trust_env=False, timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                log.warning("LLM 意图识别失败 HTTP %s: %s", resp.status_code, resp.text[:200])
                return None
            data = resp.json()
            raw_content = data["choices"][0]["message"]["content"].strip()

            raw_content = re.sub(r"^```(?:json|bash)?\s*", "", raw_content, flags=re.IGNORECASE)
            raw_content = re.sub(r"\s*```$", "", raw_content).strip()

            try:
                parsed = json.loads(raw_content)
                if isinstance(parsed, dict) and "action" in parsed:
                    return parsed
            except Exception:
                if "/sim" in raw_content:
                    sim_m = re.search(r"/sim\s+[^\n]+", raw_content)
                    cmd = sim_m.group(0).strip() if sim_m else raw_content
                    return {
                        "action": "sim",
                        "command": cmd,
                        "url": "",
                        "reply": "局面已载入。……开始推演。"
                    }
                log.warning("无法解析意图 JSON: %s", raw_content)
                return None
    except Exception as exc:
        log.warning("LLM 意图请求异常: %s", exc)
        return None

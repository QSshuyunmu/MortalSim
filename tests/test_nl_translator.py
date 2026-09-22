import asyncio, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from nl_translator import route_user_intent
from parser import parse_sim_command

CFG = {
    "enabled": True,
    "base_url": "http://43.159.137.49:8317/v1",
    "api_key": "sk-share2-5cde90ee4a02",
    "model": "gemini-3.8-flash-high",
    "timeout": 15.0,
}

def test_intent_cancel():
    async def _run():
        nl = "可以把刚刚那个任务取消吗？"
        res = await route_user_intent(nl, CFG)
        assert res is not None
        assert res.get("action") == "cancel"
        assert len(res.get("reply", "")) > 0
    asyncio.run(_run())

def test_intent_sim():
    async def _run():
        nl = "东一局平场，南家手牌2357m5689p230s77z 宝牌为西，亲第一打为中/7z，模拟决策有 1.碰中打9p，2.碰中打0s，3.不碰"
        res = await route_user_intent(nl, CFG)
        assert res is not None
        assert res.get("action") == "sim"
        cmd = res.get("command", "")
        assert cmd.startswith("/sim")
        req, err = parse_sim_command(cmd)
        assert err is None, f"Generated command cannot be parsed: {err}"
        assert req["target_seat"] == 1
    asyncio.run(_run())

def test_intent_state():
    async def _run():
        nl = "现在排队的人多吗？"
        res = await route_user_intent(nl, CFG)
        assert res is not None
        assert res.get("action") == "state"
    asyncio.run(_run())

def test_intent_qa():
    async def _run():
        nl = "无筋4和筋2哪个更危险？"
        res = await route_user_intent(nl, CFG)
        assert res is not None
        assert res.get("action") in ("qa", "chat")
        assert len(res.get("reply", "")) > 0
    asyncio.run(_run())

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
    "model": "gemini-3.5-flash-lite",
    "timeout": 25.0,
}

def test_intent_cancel():
    async def _run():
        res = await route_user_intent("可以把刚刚那个任务取消吗？", CFG)
        assert res is not None
        assert res.get("action") == "cancel"
    asyncio.run(_run())

def test_free_creative_pinfu_chinitsu_prompt():
    # 验证模型能否在轻度底线约束下自由发挥推理，构造合法的 14 张平胡/清一色手牌
    async def _run():
        res = await route_user_intent("构造一个已经平胡听牌 但是清一色一向的牌 东家 2巡 进行模拟", CFG)
        assert res is not None
        assert res.get("action") == "sim"
        cmd = res.get("command", "")
        assert cmd.startswith("/sim")
        req, err = parse_sim_command(cmd)
        assert err is None, f"Command syntax error: {err}"
        assert len(req["hand"]) == 28, f"Hand must be 14 tiles (28 chars), got {len(req['hand'])}"
    asyncio.run(_run())

def test_free_creative_kyuren_prompt():
    # 验证纯正九莲自由构造
    async def _run():
        res = await route_user_intent("随便构建一个纯正九莲听牌，亲第一打，50局", CFG)
        assert res is not None
        assert res.get("action") == "sim"
        cmd = res.get("command", "")
        req, err = parse_sim_command(cmd)
        assert err is None
        assert len(req["hand"]) == 28
    asyncio.run(_run())

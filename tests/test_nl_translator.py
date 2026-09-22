import asyncio, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from nl_translator import translate_natural_language
from parser import parse_sim_command

CFG = {
    "enabled": True,
    "base_url": "http://43.159.137.49:8317/v1",
    "api_key": "sk-share2-5cde90ee4a02",
    "model": "gemini-3.8-flash-high",
    "timeout": 15.0,
}

def test_complex_natural_language_pon():
    async def _run():
        nl = "东一局平场，南家手牌2357m5689p230s77z 宝牌为西，亲第一打为中/7z，模拟决策有 1.碰中打9p，2.碰中打0s，3.不碰"
        res = await translate_natural_language(nl, CFG)
        assert res is not None
        assert res.startswith("/sim")
        assert "2357m5689p230s77z" in res
        assert "seat=南" in res or "seat=1" in res
        req, err = parse_sim_command(res)
        assert err is None, f"Generated command cannot be parsed: {err}"
        assert req["target_seat"] == 1
        assert any(c.get("pon") and c.get("follow_up_discard") == "9p" for c in req["discards"])
        assert any(c.get("pon") and c.get("follow_up_discard") == "0s" for c in req["discards"])
        assert any(c.get("pass") for c in req["discards"])
    asyncio.run(_run())

def test_simple_natural_language():
    async def _run():
        nl = "123456789m789s12p 宝牌8p"
        res = await translate_natural_language(nl, CFG)
        assert res is not None
        assert res.startswith("/sim")
        req, err = parse_sim_command(res)
        assert err is None
        assert req["dora"] == "7p"
    asyncio.run(_run())

def test_missing_dora_prompt():
    async def _run():
        nl = "南家手牌2357m5689p230s77z，亲第一打中，碰打9p还是0s"
        res = await translate_natural_language(nl, CFG)
        assert res is not None
        assert "宝牌" in res
    asyncio.run(_run())

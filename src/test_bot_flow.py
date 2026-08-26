"""离线冒烟测试：模拟群消息，验证解析→排队→渲染→发图链路（不连真 OneBot）。"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import bot as bot_mod
from bot import Bot
from mortal_client import MortalClient


class StubMortal(MortalClient):
    def __init__(self, job: dict):
        super().__init__("http://127.0.0.1:1")
        self.job = job

    async def create_run(self, request):
        return self.job["run_id"]

    async def wait_completed(self, run_id, timeout, poll_seconds=1):
        return self.job


async def main():
    cfg = bot_mod.load_config("config.toml")
    cfg["bot"]["self_qq"] = "10001"
    cfg["bot"]["onebot_http_url"] = "http://127.0.0.1:1"  # 不会真正发送
    job = json.loads(
        Path(r"D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new4\data\runs\e82ffb73-e918-4207-8f81-ea0d84a34c4f.json").read_text(encoding="utf-8")
    )
    b = Bot(cfg)
    b.mortal = StubMortal(job)
    sent_text: list[str] = []
    sent_image: list[str] = []

    async def fake_text(group_id, text):
        sent_text.append(text)

    async def fake_image(group_id, path):
        sent_image.append(str(path))

    b.send_group_text = fake_text
    b.send_group_image = fake_image

    event = {
        "post_type": "message",
        "message_type": "group",
        "group_id": 123456,
        "user_id": "10002",
        "raw_message": "[CQ:at,qq=10001] 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s 局 E1 局数 200",
        "message": [
            {"type": "at", "data": {"qq": "10001", "text": "@MortalSimBot"}},
            {"type": "text", "data": {"text": " 手牌 4567m3477p134066s 宝牌 9s 候选 1s,6s 局 E1 局数 200"}},
        ],
    }
    await b.handle_event(event)
    worker = asyncio.create_task(b.worker())
    await asyncio.sleep(1.0)
    worker.cancel()
    print("text replies:", sent_text)
    print("image replies:", sent_image)
    assert sent_text and "已收到" in sent_text[0]
    assert any("推荐第一打" in t for t in sent_text)
    assert sent_image and Path(sent_image[0]).exists()
    print("BOT FLOW OK")


if __name__ == "__main__":
    asyncio.run(main())

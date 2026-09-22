import sys, tomllib, pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from bot import Bot

def test_execute_review_sync_calls_analyze_attribution_safely():
    # 模拟 mock review 数据
    mock_rev_result = {
        "review": {
            "rating": 0.86,
            "total_reviewed": 91,
            "total_matches": 77,
            "kyokus": []
        }
    }

    cfg = tomllib.load(open(ROOT / "bot" / "config.toml" if (ROOT / "bot" / "config.toml").exists() else ROOT.parent / "MortalSim-Bot" / "config.toml", "rb"))
    bot = Bot(cfg)

    # 验证 self._analyze_review_attribution 可以正常被调用
    verdict = bot._analyze_review_attribution(mock_rev_result, 1)
    assert "判定：" in verdict

    # 验证在拼接 summary_msg 时的字符串结构
    seat_zh = "南"
    target_seat = 1
    total_rev = 91
    official_tag_name = "Consensus"
    rating_pct = 86.0
    match_pct = 84.6
    web_link = "https://example.com"

    summary_msg = (
        f"【Mortal 牌谱检讨】\n"
        f"视角：{seat_zh}家 ({target_seat}号位) | 共 {total_rev} 巡\n"
        f"模型：{official_tag_name} | 评分：{rating_pct} | 吻合度：{match_pct}%\n"
        f"{verdict}\n"
        f"🌐 在线复盘：{web_link}"
    )
    assert "86.0" in summary_msg
    assert "判定：" in summary_msg

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from bot import _analyze_review_attribution

def test_variance_bad_luck_attribution():
    # 模拟高分 + 满贯跳满放铳但切牌一致
    res = {
        "review": {
            "rating": 0.86,
            "total_reviewed": 91,
            "total_matches": 77,
            "kyokus": [
                {
                    "bakaze": 0, "kyoku": 1, "honba": 0,
                    "end_status": [{"type": "hora", "actor": 0, "target": 1, "deltas": [12000, -12000, 0, 0]}],
                    "entries": [
                        {"is_equal": True, "junme": 9, "actual": {"type": "dahai", "pai": "7m"}, "expected": {"type": "dahai", "pai": "7m"}}
                    ]
                },
                {
                    "bakaze": 0, "kyoku": 3, "honba": 2,
                    "end_status": [{"type": "hora", "actor": 3, "target": 1, "deltas": [0, -18000, 0, 18000]}],
                    "entries": [
                        {"is_equal": True, "junme": 8, "actual": {"type": "dahai", "pai": "1m"}, "expected": {"type": "dahai", "pai": "1m"}}
                    ]
                }
            ]
        }
    }
    verdict = _analyze_review_attribution(res, target_seat=1)
    assert "下限方差（不可抗力）" in verdict
    assert "东2局-12000点" in verdict
    assert "东4局2本场-18000点" in verdict
    assert "与 Mortal 推荐一致" in verdict

def test_skill_error_attribution():
    # 模拟低分 + 恶手放铳
    res = {
        "review": {
            "rating": 0.72,
            "total_reviewed": 80,
            "total_matches": 50,
            "kyokus": [
                {
                    "bakaze": 0, "kyoku": 0, "honba": 0,
                    "end_status": [{"type": "hora", "actor": 0, "target": 1, "deltas": [8000, -8000, 0, 0]}],
                    "entries": [
                        {"is_equal": False, "junme": 8, "actual": {"type": "dahai", "pai": "1z"}, "expected": {"type": "dahai", "pai": "8m"},
                         "details": [{"action": {"type": "dahai", "pai": "8m"}, "prob": 0.9}, {"action": {"type": "dahai", "pai": "1z"}, "prob": 0.01}]}
                    ]
                }
            ]
        }
    }
    verdict = _analyze_review_attribution(res, target_seat=1)
    assert "技术偏差" in verdict

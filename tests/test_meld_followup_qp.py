"""Portable tests for second-stage meld-follow-up Q/P semantics."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

import math
from model_eval import _conditional_discard_view


def test_follow_up_distribution_is_conditional_over_legal_discards():
    response = {"type": "dahai", "pai": "9s", "meta": {"mask_bits": sum(1 << i for i in (0, 8, 26, 33)), "q_values": [0.0, 1.0, 2.0, 3.0]}}
    result = _conditional_discard_view(response, {"follow_up_discard": None})
    assert result["mode"] == "model"
    assert result["response_tile"] == "9s"
    assert result["tile"] == "7z"
    assert math.isclose(sum(v["p"] for v in result["distribution"].values()), 1.0)
    assert result["distribution"]["7z"]["p"] > result["distribution"]["1m"]["p"]


def test_explicit_follow_up_keeps_its_own_probability_and_does_not_change_argmax():
    response = {"type": "dahai", "pai": "9s", "meta": {"mask_bits": (1 << 26) | (1 << 30), "q_values": [2.0, 1.0]}}
    # 显式测试 tau=1.0 下的标准 Softmax: 1 / (1 + e)
    result_tau1 = _conditional_discard_view(response, {"follow_up_discard": "4z"}, tau=1.0)
    assert result_tau1["mode"] == "forced"
    assert result_tau1["model_tile"] == "9s"
    assert result_tau1["tile"] == "4z"
    assert math.isclose(result_tau1["p"], 1 / (1 + math.e), rel_tol=1e-6)

    # 默认 tau=0.1: 1 / (1 + e^10)
    result_default = _conditional_discard_view(response, {"follow_up_discard": "4z"})
    assert math.isclose(result_default["p"], 1 / (1 + math.exp(10)), rel_tol=1e-6)


def test_forced_follow_up_must_be_in_the_legal_mask():
    response = {"type": "dahai", "pai": "9s", "meta": {"mask_bits": 1 << 26, "q_values": [2.0]}}
    try:
        _conditional_discard_view(response, {"follow_up_discard": "4z"})
    except ValueError as exc:
        assert "mask" in str(exc)
    else:
        raise AssertionError("illegal forced discard was accepted")

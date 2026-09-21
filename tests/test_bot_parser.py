"""Focused tests for /sim chi candidate syntax and call-target rivers."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))

from parser import parse_sim_command  # noqa: E402


BASE = "/sim 1233567889m9s24z d9p c={candidate},pass x=2 S4-0 seat=东 P116,290,416,178 1000"


def parse(candidate: str):
    request, error = parse_sim_command(BASE.format(candidate=candidate))
    assert error is None, error
    assert request is not None
    return request


def test_chi_target_shorthand_infers_consumed_tiles_and_forces_call_river():
    request = parse("chi1m>9s")
    chi = request["discards"][0]

    assert chi["chi"] == ["2m", "3m"]
    assert chi["call_tile"] == "1m"
    assert chi["follow_up_discard"] == "9s"
    assert chi["candidate"] == "chi:2m3m>9s"
    # East is the first player at x=2, so the responsive discard is the
    # previous round's last player (North), not a newly generated x=2 discard.
    assert request["target_seat"] == 3  # South 4 dealer's absolute ID
    assert request["opponent_rivers"][2][-1][0] == "1m"
    assert [len(r) for r in request["opponent_rivers"]] == [1, 1, 1, 0]


@pytest.mark.parametrize("candidate", ["chi:1m>9s", "吃1m>9s"])
def test_chi_target_shorthand_accepts_colon_and_chinese_prefix(candidate):
    chi = parse(candidate)["discards"][0]
    assert chi["chi"] == ["2m", "3m"]
    assert chi["call_tile"] == "1m"


def test_chi_explicit_consumed_tiles_remain_supported():
    chi = parse("chi:23m(1m)>9s")["discards"][0]
    assert chi["chi"] == ["2m", "3m"]
    assert chi["call_tile"] == "1m"
    assert chi["follow_up_discard"] == "9s"


def test_chi_target_shorthand_rejects_unavailable_sequence():
    request, error = parse_sim_command(
        "/sim 1233567889m9s24z d9p c=chi:4p>9s,pass x=2 S4-0 seat=东 P116,290,416,178 1000"
    )
    assert request is None
    assert error is not None
    assert "吃牌错误" in error
    assert "4p" in error


def test_chi_target_shorthand_auto_expands_multiple_sequences():
    request, error = parse_sim_command(
        "/sim 123345m678p789s1z d9p c=chi:3m>9s,pass x=2 S4-0 seat=东 P116,290,416,178 1000"
    )
    assert error is None
    assert request is not None
    # 3m can be called with 12m or 45m -> 2 chi candidates + 1 pass candidate
    candidates = [c.get("candidate", "pass") for c in request["discards"]]
    assert "chi:1m2m>9s" in candidates
    assert "chi:4m5m>9s" in candidates
    assert "pass" in candidates


def test_chi_explicit_call_tile_with_brackets_and_at():
    cmd = "/sim 1233567889m9s24z d9p c=chi:23m(4m)>9s,chi:35m>9s,chi:56m@4m>9s,pass x=2 S4-0 seat=东 P116,290,416,178 1000"
    request, error = parse_sim_command(cmd)
    assert error is None
    candidates = [c.get("candidate", "pass") for c in request["discards"]]
    assert candidates == ["chi:2m3m>9s", "chi:3m5m>9s", "chi:5m6m>9s", "pass"]
    assert request["opponent_rivers"][2][-1][0] == "4m"


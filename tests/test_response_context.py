"""Portable response-context regression tests: no torch/libriichi/network needed."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot" / "src"))
from parser import parse_sim_command
from mortal_app.call_context import response_context, response_events
from render_png import _table_snapshot, candidate_label

COMMAND = "/sim 12334567889m9s4z d9p c=chi:3m,pon:3m,pass x=2 S4-0 seat=东 P116,290,416,178 200"


def parse(command=COMMAND):
    req, error = parse_sim_command(command)
    assert error is None, error
    return req


@pytest.mark.parametrize("round_id", ["E1", "E2", "E3", "E4", "S1", "S4"])
def test_east_first_turn_never_has_a_response(round_id):
    req, error = parse_sim_command(COMMAND.replace("x=2", "x=1").replace("S4", round_id))
    assert req is None
    assert "第1巡尚无上家弃牌" in error


@pytest.mark.parametrize("round_id", ["E1", "S2", "W3", "S4"])
@pytest.mark.parametrize("wind,name", enumerate("东南西北"))
def test_wind_to_absolute_conversion_and_response_prefix(round_id, wind, name):
    req = parse(COMMAND.replace("S4", round_id).replace("seat=东", f"seat={name}"))
    ct = response_context(req)
    oya = int(round_id[1]) - 1
    assert req["target_seat"] == (oya + wind) % 4
    assert ct["target_actor"] == (oya + wind + 3) % 4
    assert ct["tile"] == "3m"
    assert [len(ct["rivers"][(oya + w) % 4]) for w in range(4)] == [1 + int(w < wind) for w in range(4)]
    ev = response_events(req, ct)
    assert ev[0]["oya"] == oya
    assert ev[-1] == {"type": "dahai", "actor": ct["target_actor"], "pai": "3m", "tsumogiri": False}
    assert sum(e["type"] == "tsumo" and e["actor"] == req["target_seat"] for e in ev) == 1
    snapshot = _table_snapshot({"config": req, "candidates": [{"candidate": "pass"}]})
    assert snapshot["target_wind"] == wind
    assert snapshot["response"]["tile"] == "3m"


def test_automatic_and_explicit_chi_share_one_world():
    auto = parse()
    explicit = parse(COMMAND.replace("chi:3m", "chi:1m2m"))
    for key in ("target_seat", "opponent_rivers", "target_past_discards", "scores"):
        assert explicit[key] == auto[key]
    assert [c["chi"] for c in auto["discards"] if c.get("chi")] == [["1m", "2m"], ["2m", "4m"], ["4m", "5m"]]
    assert all(c.get("follow_up_discard") is None for c in auto["discards"])


@pytest.mark.parametrize("changes,match", [
    ({"x": 1}, "第1巡"),
    ({"opponent_rivers": None}, "四家牌河"),
    ({"hand": "12334567889m9s44z"}, "13张"),
    ({"prefix_melds": [{"type": "pon"}]}, "已有副露"),
])
def test_backend_boundary_rejects_forged_request(changes, match):
    req = parse()
    req.update(changes)
    with pytest.raises(ValueError, match=match):
        response_context(req)


@pytest.mark.parametrize("mutation,match", [("wrong_tile", "不一致"), ("future", "禁止静默截断"), ("no_pair", "不足"), ("missing_consumed", "搭子不在"), ("bad_follow", "剩余手牌")])
def test_illegal_response_is_not_a_numeric_candidate(mutation, match):
    req = parse()
    if mutation == "wrong_tile":
        req["opponent_rivers"][2][-1] = ("6z", False, False)
    elif mutation == "future":
        req["opponent_rivers"][2].append(("6z", False, False))
    elif mutation == "no_pair":
        req["hand"] = req["hand"].replace("3m3m", "3m6z")
    elif mutation == "missing_consumed":
        req["hand"] = req["hand"].replace("1m", "6z")
    else:
        req["discards"][0]["follow_up_discard"] = "1m"
    with pytest.raises(ValueError, match=match):
        response_context(req)


def test_explicit_river_conflict_not_overwritten():
    req, error = parse_sim_command(COMMAND.replace(" 200", " river=北:6z 200"))
    assert req is None
    assert "同一张上家弃牌" in error


def test_candidates_cannot_name_different_discard_worlds():
    req, error = parse_sim_command(COMMAND.replace("pon:3m", "pon:8m"))
    assert req is None
    assert "同一张" in error


def test_ambiguous_consumed_pair_needs_target():
    req, error = parse_sim_command(COMMAND.replace("chi:3m,pon:3m", "chi:23m"))
    assert req is None
    assert "多个目标" in error


def test_report_missing_prefix_fails_instead_of_empty_first_turn():
    req = parse()
    del req["x"]
    with pytest.raises(ValueError, match="不能渲染"):
        _table_snapshot({"config": req, "candidates": [{"candidate": "pass"}]})


def test_pon_identity_survives_service_normalization():
    from mortal_app.service import normalize_candidate
    candidate = parse()["discards"][3]
    assert normalize_candidate(candidate)["candidate"] == "pon:3m"
    assert normalize_candidate(candidate)["call_tile"] == "3m"
    assert candidate_label(normalize_candidate(candidate)) == "碰 3m"


def test_backend_rejects_before_native_or_model_import(monkeypatch):
    import mortal_app.service as service
    monkeypatch.setattr(service, "_prepare_imports", lambda *_: pytest.fail("native loading reached"))
    request = parse()
    request["x"] = 1
    with pytest.raises(ValueError, match="第1巡"):
        service._parse_inputs(request)


def test_pon_follow_up_cannot_discard_the_red_five_consumed_by_runner():
    req, error = parse_sim_command("/sim 12550m678p789s11z d9p c=pon:5m>0m,pass x=2 E1 seat=东 200")
    assert req is None
    assert "剩余手牌" in error


def test_native_follow_up_checks_mask_not_only_validate_reaction(monkeypatch):
    import types
    from mortal_app.call_context import validate_native_response
    class State:
        def __init__(self, target):
            pass
        def update(self, event):
            pass
        def validate_reaction(self, event):
            pass  # Native method alone does not enforce kuikae.
        def encode_obs(self, version, at_kan_select):
            mask = [True] * 46
            mask[2] = False  # 3m is forbidden immediately after calling 3m.
            return None, mask
    native = types.ModuleType("libriichi.state")
    native.PlayerState = State
    monkeypatch.setitem(sys.modules, "libriichi.state", native)
    req = parse(COMMAND.replace("chi:3m,pon:3m,pass", "chi:1m2m>3m"))
    with pytest.raises(ValueError, match="喰替"):
        validate_native_response(req, response_context(req))


def test_raw_pass_spellings_cannot_bypass_response_validation():
    for candidates in ("pass", ["pass"], [{"pass_action": True}]):
        req = parse()
        req.update(x=1, discards=candidates)
        with pytest.raises(ValueError, match="第1巡"):
            response_context(req)


def test_corrected_response_history_has_a_new_semantic_namespace(monkeypatch):
    from mortal_app.history_store import compute_canonical_fingerprint
    import mortal_app.call_context as context_module
    req = parse()
    corrected = compute_canonical_fingerprint(req)
    # Negative control: old fingerprint had no response-semantics version.
    monkeypatch.setattr(context_module, "kind", lambda _: "discard")
    assert compute_canonical_fingerprint(req) != corrected


def test_prefix_reconstructs_final_hand_without_self_draw():
    req = parse()
    ct = response_context(req)
    events = response_events(req, ct)
    target = ct["target_seat"]
    hand = list(events[0]["tehais"][target])
    for event in events[1:]:
        if event["actor"] != target:
            continue
        if event["type"] == "tsumo":
            hand.append(event["pai"])
        elif event["type"] == "dahai":
            hand.remove(event["pai"])
    assert sorted(hand) == sorted(["1m", "2m", "3m", "3m", "4m", "5m", "6m", "7m", "8m", "8m", "9m", "9s", "N"])


def test_qp_receives_full_prefix_and_preserves_concrete_model(monkeypatch):
    import bot
    import model_eval
    seen = []
    monkeypatch.setattr(model_eval, "eval_model_qp", lambda **kw: seen.append(kw) or {})
    b = object.__new__(bot.Bot)
    b.mortal_cfg = {"model_id": "distill_41b_infer"}
    req = parse()
    req["model_id"] = "distill_nova"
    b._eval_model_qp(req)
    assert seen[0]["model_id"] == "distill_nova"
    assert seen[0]["target_seat"] == 3
    assert seen[0]["response_prefix"][-1]["pai"] == "3m"
    assert seen[0]["response_prefix"][0]["oya"] == 3

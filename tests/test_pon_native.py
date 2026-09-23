"""Optional native pon checks. Run after rebuilding libriichi (no model/GPU)."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot/src"))
libriichi = pytest.importorskip("libriichi", reason="optional native extension is not built")
if not hasattr(libriichi, "state"):
    pytest.skip("libriichi source namespace is not a compiled extension", allow_module_level=True)

from mortal_app.call_context import mjai, pon_consumed, response_context, response_events, validate_native_response
from .test_pon_matrix import TILES, command, parse


@pytest.mark.parametrize("round_id", [f"{w}{n}" for w in "ESW" for n in range(1, 5)])
@pytest.mark.parametrize("wind,delta", [(w, d) for w in range(4) for d in (1, 2, 3)])
def test_native_source_seat_matrix(round_id, wind, delta):
    req = parse(command(round_id, wind, (wind + delta) % 4))
    validate_native_response(req, response_context(req))


@pytest.mark.parametrize("called", TILES + ["0m", "0p", "0s"])
def test_native_all_called_tiles(called):
    req = parse(command(called=called))
    validate_native_response(req, response_context(req))


@pytest.mark.parametrize("suit", "mps")
def test_native_exact_red_consumption_and_remaining_discard_masks(suit):
    normal, red = f"5{suit}", f"0{suit}"
    req = parse(command(called=normal, pair=[red, normal, normal]))
    ct = response_context(req)
    validate_native_response(req, ct)
    for c in req["discards"][:2]:
        st = libriichi.state.PlayerState(ct["target_seat"])
        for e in response_events(req, ct):
            st.update(json.dumps(e))
        consumed = pon_consumed(ct["hand"], ct["tile"], c.get("pon_consumed"))
        st.update(json.dumps({"type": "pon", "actor": ct["target_seat"], "target": ct["target_actor"],
                              "pai": mjai(ct["tile"]), "consumed": list(map(mjai, consumed))}))
        _, mask = st.encode_obs(4, False)
        # Retaining the red five does NOT permit discarding it immediately (kuikae).
        assert not mask[34 + "mps".index(suit)]
        assert not mask[4 + 9 * "mps".index(suit)]


class MaskPolicy:
    """Deterministic legal test policy, not a Mortal model or EV estimate."""
    version = 4
    decision_contract = "stable_advantage_v2"
    enable_rule_based_agari_guard = False
    def react_batch(self, obs, masks, *args):
        masks = [list(map(bool, row)) for row in masks]
        qs = [[(-1000.0 if not yes else (100.0 if i == 43 else float(46 - i))) for i, yes in enumerate(row)] for row in masks]
        actions = [max(range(46), key=q.__getitem__) for q in qs]
        return actions, qs, masks, [True] * len(masks)


def simulate(req, c, monkeypatch, *, forced_follow=None, count=2):
    monkeypatch.setenv("MORTAL_TRACE_EVENTS", "1")
    from mortal_app.service import _parse_inputs
    req = {**req, "seed": 23, "batch_size": 4, "rayon_threads": 2}
    hand, draw, dora, _, _, _, ctx, _, _, prefix = _parse_inputs(req)
    ct = response_context(req)
    return libriichi.arena.CustomKyokuRunner().run_many(
        engine=MaskPolicy(), kyoku=ctx["kyoku"], honba=0, kyotaku=0,
        bakaze=ctx["bakaze"], oya=ctx["oya"], scores=ctx["scores"], dora_marker=dora,
        main_haipai=hand, first_discard="1m", first_tsumo=draw,
        seed_start=(23, 0xDEAD), count=count, target_seat=prefix["target_seat"], x=prefix["x"],
        target_past_discards=prefix["target_past_discards"], opponent_rivers=prefix["opponent_rivers"],
        first_pon=bool(c.get("pon")), first_pass=bool(c.get("pass")),
        first_pon_consumed=list(map(mjai, pon_consumed(ct["hand"], ct["tile"], c.get("pon_consumed")))) if c.get("pon") else None,
        first_follow_up_discard=forced_follow,
    )


@pytest.mark.parametrize("source", [0, 1, 2])
def test_native_trace_executes_each_pair_on_the_right_discard(source, monkeypatch):
    req = parse(command(source=source, called="5m", pair=["0m", "5m", "5m"]))
    ct = response_context(req)
    for c in req["discards"][:2]:
        for row in simulate(req, c, monkeypatch):
            assert not row["result"].get("error"), row["result"]
            ev = [json.loads(e) for e in row["trace_events"]]
            meld = next(e for e in ev if e["type"] == "pon" and e["actor"] == ct["target_seat"])
            assert meld["target"] == ct["target_actor"]
            assert meld["consumed"] == list(map(mjai, c["pon_consumed"]))
            next_self = next(e for e in ev[ev.index(meld) + 1:] if e.get("actor") == ct["target_seat"])
            assert next_self["type"] == "dahai"  # no fictitious post-call draw


@pytest.mark.parametrize("illegal", ["7z", "5mr"])
def test_native_forced_bad_followup_fails_instead_of_ai_fallback(illegal, monkeypatch):
    req = parse(command(called="5m", pair=["0m", "5m", "5m"]))
    rows = simulate(req, req["discards"][1], monkeypatch, forced_follow=illegal, count=1)
    assert rows[0]["result"].get("error") == "first_meld_follow_up_invalid", rows[0]


def test_native_pass_does_not_slide_to_a_later_call(monkeypatch):
    req = parse(command(called="5m", pair=["0m", "5m", "5m"]))
    ct = response_context(req)
    for row in simulate(req, req["discards"][-1], monkeypatch):
        assert not row["result"].get("error"), row["result"]
        ev = [json.loads(e) for e in row["trace_events"]]
        boundary = next(i for i, e in enumerate(ev) if e["type"] == "dahai" and e["actor"] == ct["target_actor"] and e["pai"] == "5m")
        next_self = next(e for e in ev[boundary + 1:] if e.get("actor") == ct["target_seat"])
        assert next_self["type"] == "tsumo"

"""Pon matrix: portable parser/API/identity/QP checks; no native/GPU imports."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bot/src"))
from parser import parse_sim_command
from mortal_app.call_context import base, pon_consumed, pon_id, pon_options, response_context, response_events

TILES = [f"{n}{s}" for s in "mps" for n in range(1, 10)] + [f"{n}z" for n in range(1, 8)]


def command(round_id="E1", wind=3, source=0, called="5p", pair=None, candidate=None, x=2):
    pair = pair or [base(called)] * 2
    fillers = [t for t in TILES if base(t) != base(called) and t != "9p"][:13 - len(pair)]
    hand = pair + fillers
    # End after any opponent's discard following our own (x-1)th discard.
    total = ((x - 2) * 4 + wind + 1 + (source - wind) % 4) if x > 1 else source + 1
    rivers = [[] for _ in range(4)]
    pool = iter(t for t in reversed(TILES) if base(t) not in {base(h) for h in hand} and t != "9p")
    for i in range(total):
        rivers[i % 4].append(called if i == total - 1 else next(pool))
    river = "/".join(f"{'东南西北'[i]}:{','.join(row)}" for i, row in enumerate(rivers))
    return (f"/sim {''.join(hand)} d1p seat={'东南西北'[wind]} x={x} {round_id} "
            f"river={river} c={candidate or 'pon:' + called + ',pass'} 1")


def parse(cmd):
    req, error = parse_sim_command(cmd)
    assert error is None, error
    return req


@pytest.mark.parametrize("round_id", [f"{w}{n}" for w in "ESW" for n in range(1, 5)])
@pytest.mark.parametrize("wind,delta", [(w, d) for w in range(4) for d in (1, 2, 3)])
def test_every_wind_round_and_pon_source(round_id, wind, delta):
    source = (wind + delta) % 4
    req = parse(command(round_id, wind, source))
    ct = response_context(req)
    oya = int(round_id[1]) - 1
    assert ct["target_actor"] == (oya + source) % 4
    assert ct["target_seat"] == (oya + wind) % 4
    ev = response_events(req, ct)
    assert ev[-1]["type"] == "dahai" and ev[-1]["actor"] == ct["target_actor"]
    assert ev[-1]["pai"] == "5p"
    assert sum(e["type"] == "dahai" and e["actor"] == ct["target_seat"] for e in ev) == 1


@pytest.mark.parametrize("wind,source", [(w, s) for w in (1, 2, 3) for s in range(w)])
def test_first_turn_can_pon_any_opponent_who_has_already_discarded(wind, source):
    req = parse(command(wind=wind, source=source, x=1))
    assert response_context(req)["rivers"][req["target_seat"]] == []


@pytest.mark.parametrize("called", TILES + ["0m", "0p", "0s"])
def test_all_34_kinds_and_three_red_called_tiles(called):
    req = parse(command(called=called))
    ct = response_context(req)
    assert ct["tile"] == called
    assert pon_consumed(ct["hand"], called) == [base(called)] * 2


@pytest.mark.parametrize("suit", "mps")
@pytest.mark.parametrize("source", [0, 1, 2])
def test_red_and_normal_consumption_auto_expands_without_probability_split(suit, source):
    red, normal = f"0{suit}", f"5{suit}"
    req = parse(command(source=source, called=normal, pair=[red, normal, normal]))
    cs = req["discards"]
    assert [c.get("pon_consumed") for c in cs[:2]] == [[red, normal], [normal, normal]]
    assert [c["candidate"] for c in cs[:2]] == [f"pon:{normal}@{red}{normal}", f"pon:{normal}@{normal}{normal}"]
    from mortal_app.service import normalize_candidate, candidate_identity
    from apps.api.models import DiscardCandidate
    from render_png import candidate_label
    for c in cs[:2]:
        assert normalize_candidate(c)["pon_consumed"] == c["pon_consumed"]
        assert normalize_candidate(c)["candidate"] == c["candidate"]
        assert DiscardCandidate(**c).candidate_id == c["candidate"]
        bare = {k: v for k, v in c.items() if k != "candidate"}
        assert candidate_identity(bare) == c["candidate"]
        assert f"碰{normal}(" in candidate_label(c)


@pytest.mark.parametrize("pair,called,options", [
    (["5m", "5m"], "5m", [["5m", "5m"]]),
    (["0m", "5m"], "5m", [["0m", "5m"]]),
    (["0m", "5m", "5m"], "5m", [["0m", "5m"], ["5m", "5m"]]),
    (["5m", "5m", "5m"], "0m", [["5m", "5m"]]),
    (["3z", "3z", "3z"], "3z", [["3z", "3z"]]),
])
def test_physical_pairs_not_permutations(pair, called, options):
    assert pon_options(pair, called) == options
    parse(command(called=called, pair=pair))


@pytest.mark.parametrize("syntax", ["pon", "pon>8s", "PON:5p", "碰5p", "碰5p>8s"])
def test_shorthand_binds_explicit_latest_discard_even_with_multiple_pairs(syntax):
    cmd = command(candidate=syntax + ",pass").replace("1m2m", "1m1m")
    if ">8s" in syntax:
        cmd = cmd.replace("9m", "8s", 1)
    req = parse(cmd)
    assert req["discards"][0]["call_tile"] == "5p"


@pytest.mark.parametrize("syntax,expected", [
    ("pon:5m@05m", ["0m", "5m"]),
    ("pon:5m@55m", ["5m", "5m"]),
    ("pon:5m@5m0m", ["0m", "5m"]),
])
def test_explicit_pair_selection(syntax, expected):
    req = parse(command(called="5m", pair=["0m", "5m", "5m"], candidate=syntax))
    assert req["discards"][0]["pon_consumed"] == expected


@pytest.mark.parametrize("syntax", ["pon:5mBAD", "pon:5m>1p>2p", "pon:55m", "pon:", "pon:5m@0m", "pon:5m@00m", "pon:5m@1m2m"])
def test_malformed_or_impossible_consumption_rejected(syntax):
    # pon: without a tile is treated as bare pon, so use no river for that form.
    cmd = command(called="5m", pair=["0m", "5m", "5m"], candidate=syntax)
    if syntax == "pon:":
        cmd = cmd.replace("pon:", "pon:>")
    req, err = parse_sim_command(cmd)
    assert req is None and err


@pytest.mark.parametrize("follow", ["0m", "5m", "7z"])
def test_no_kuikae_or_nonexistent_followup(follow):
    req, err = parse_sim_command(command(called="5m", pair=["0m", "5m", "5m"], candidate=f"pon:5m@55m>{follow}"))
    assert req is None and ("喰替" in err if follow != "7z" else "剩余手牌" in err)


@pytest.mark.parametrize("suit", "mps")
@pytest.mark.parametrize("red_source", [False, True])
def test_generated_river_reserves_called_and_dora_physical_tiles(suit, red_source):
    from parser import _generate_default_rivers
    from mortal_app.call_context import base
    hand = [f"0{suit}", f"5{suit}", f"5{suit}"] + [t for t in TILES if t[-1] != suit and t != "4p"][:10]
    called = f"0{suit}" if red_source else f"5{suit}"
    # A red source needs 3 ordinary fives in hand instead of our red five.
    if red_source:
        hand[0] = f"5{suit}"
    args = (hand, 3, 0, 4)
    first = _generate_default_rivers(*args, call_target_tile=called, dora_indicator="4p")
    assert first == _generate_default_rivers(*args, call_target_tile=called, dora_indicator="4p")
    past, rivers = first
    visible = hand + ["4p"] + [v[0] for v in past] + [v[0] for row in rivers for v in row]
    from collections import Counter
    assert max(Counter(map(base, visible)).values()) <= 4
    assert all(visible.count(f"5{s}") <= 3 and visible.count(f"0{s}") <= 1 for s in "mps")
    assert rivers[2][-1][0] == called  # target North, kamicha West
    assert not any(t in {h for h in hand if h.endswith("z")} for t in visible[len(hand) + 1:])


def test_generated_river_rejects_impossible_called_five_with_dora_indicator():
    from parser import _generate_default_rivers
    hand = ["0m", "5m", "5m"] + [t for t in TILES if t[-1] != "m"][:10]
    with pytest.raises(ValueError, match="物理数量"):
        _generate_default_rivers(hand, 3, 0, 3, call_target_tile="5m", dora_indicator="5m")


def test_api_distinguishes_physical_pon_candidates():
    from apps.api.models import RunRequest
    req = parse(command(called="5m", pair=["0m", "5m", "5m"]))
    req.update(engine="python", decision_contract="legacy_amp_v1")
    valid = RunRequest(**req)
    ids = [c.candidate_id for c in valid.discards]
    assert ids == ["pon:5m@0m5m", "pon:5m@5m5m", "pass"]
    with pytest.raises(ValueError, match="unique|重复"):
        RunRequest(**{**req, "discards": [req["discards"][0], req["discards"][0]]})


def test_direct_api_cannot_silently_choose_red_consumption_or_bypass_daiminkan():
    req = parse(command(called="5m", pair=["0m", "5m", "5m"]))
    del req["discards"][0]["pon_consumed"]
    with pytest.raises(ValueError, match="多种"):
        response_context(req)
    req["discards"] = [{"tile": "daiminkan", "daiminkan": True}]
    with pytest.raises(ValueError, match="暂不模拟"):
        response_context(req)


def test_riichi_hand_cannot_pon_and_existing_meld_not_silently_omitted():
    req = parse(command())
    t = req["target_past_discards"][0][0]
    req["target_past_discards"][0] = (t, False, True)
    with pytest.raises(ValueError, match="立直后"):
        response_context(req)
    req = parse(command())
    req["prefix_melds"] = [{"type": "pon"}]
    with pytest.raises(ValueError, match="已有副露"):
        response_context(req)


def test_qp_uses_exact_pair_and_one_shared_parent_probability(monkeypatch):
    from model_eval import _meld_followup_qp
    req = parse(command(called="5m", pair=["0m", "5m", "5m"]))
    ct = response_context(req)
    seen = []
    class Bot:
        def __init__(self, engine, seat):
            pass
        def react(self, text):
            event = json.loads(text)
            if event["type"] == "pon":
                seen.append(event)
                q = 1.0 if "5mr" in event["consumed"] else 2.0
                return json.dumps({"type": "dahai", "pai": "1m", "meta": {"mask_bits": 1, "q_values": [q]}})
    monkeypatch.setitem(sys.modules, "libriichi", types.SimpleNamespace(mjai=types.SimpleNamespace(Bot=Bot)))
    out = _meld_followup_qp(object(), ct["target_seat"], ct["hand"], ct["tile"], response_events(req, ct), req["discards"], {"pon:5m": {"q": 0.7, "p": 0.2}, "pass": {"p": 0.8}})
    assert [e["consumed"] for e in seen] == [["5mr", "5m"], ["5m", "5m"]]
    assert all(e["target"] == ct["target_actor"] for e in seen)
    for c in req["discards"][:2]:
        assert out[c["candidate"]]["p"] == 0.2
        assert out[c["candidate"]]["p_scope"] == "pon_action"
        assert out[c["candidate"]]["follow_up"]["p"] == 1.0
    assert out[req["discards"][0]["candidate"]]["follow_up"]["q"] != out[req["discards"][1]["candidate"]]["follow_up"]["q"]

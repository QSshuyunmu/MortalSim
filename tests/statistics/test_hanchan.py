from __future__ import annotations

import pytest

from mortal_app.service import (
    HANCHAN_PT_TABLES,
    MERGE_STATE_VERSION,
    _final_rank_distribution,
    _merge_hanchan,
    _resolve_next_hanchan_state,
    _summarize_hanchan,
)


class FakeModel:
    def __init__(self, probs):
        self._probs = list(probs)
        self.model_id = "fake"
        self.model_sha256 = "fake-sha"
        self.manifest = {"feature_schema": "hanchan_rank_v1"}

    def predict_seat(self, scores, bakaze, kyoku_num, honba, kyotaku, oya, seat):
        return self._probs


def context(**overrides):
    base = {
        "bakaze": "E",
        "kyoku": 1,
        "honba": 0,
        "kyotaku": 0,
        "oya": 0,
    }
    base.update(overrides)
    return base


def result(final_scores, outcome="self_win", kyotaku_remaining=0):
    return {
        "outcome": outcome,
        "type": outcome,
        "final_scores": final_scores,
        "kyotaku_remaining": kyotaku_remaining,
        "agari_actors": [],
        "agari_targets": [],
    }


def row(seed, final_scores, outcome="self_win", metrics=None):
    return {
        "seed": [seed, 0xDEAD],
        "result": result(final_scores, outcome),
        "metrics": metrics or {},
    }


def test_final_rank_distribution_uses_earliest_seat_tie_break() -> None:
    assert _final_rank_distribution([25000, 25000, 20000, 20000], 1) == [0.0, 1.0, 0.0, 0.0]
    assert _final_rank_distribution([25000, 25000, 25000, 25000], 3) == [0.0, 0.0, 0.0, 1.0]


def test_next_state_dealer_win_renchan() -> None:
    state = _resolve_next_hanchan_state(context(), result([30000, 24000, 23000, 23000]), {})
    assert state["bakaze"] == "E"
    assert state["kyoku_num"] == 1
    assert state["honba"] == 1
    assert state["oya"] == 0
    assert state["scores"] == [30000, 24000, 23000, 23000]


def test_next_state_dealer_rotate_on_other_win() -> None:
    state = _resolve_next_hanchan_state(context(), result([24000, 30000, 23000, 23000], outcome="other_tsumo"), {})
    assert state["bakaze"] == "E"
    assert state["kyoku_num"] == 2
    assert state["honba"] == 0
    assert state["oya"] == 1


def test_next_state_draw_always_adds_honba() -> None:
    state = _resolve_next_hanchan_state(context(), result([25000, 25000, 25000, 25000], outcome="draw", kyotaku_remaining=0), {"final_tenpai": False})
    assert state["kyoku_num"] == 2
    assert state["oya"] == 1
    assert state["honba"] == 1  # Tenhou data: draws add honba even on dealer rotate


def test_next_state_draw_dealer_tenpai_renchan() -> None:
    state = _resolve_next_hanchan_state(context(), result([25000, 25000, 25000, 25000], outcome="draw", kyotaku_remaining=0), {"final_tenpai": True})
    assert state["kyoku_num"] == 1
    assert state["oya"] == 0
    assert state["honba"] == 1


def test_next_state_all_last_end_rules() -> None:
    # S4, dealer rotates and leader >= 30000 -> hanchan ends.
    ctx = context(bakaze="S", kyoku=8, oya=3)
    assert _resolve_next_hanchan_state(ctx, result([24000, 25000, 31000, 20000], outcome="other_tsumo"), {}) is None
    # S4, dealer rotates and leader < 30000 -> West round.
    ctx = context(bakaze="S", kyoku=8, oya=3)
    state = _resolve_next_hanchan_state(ctx, result([24000, 25000, 29000, 22000], outcome="other_tsumo"), {})
    assert state["bakaze"] == "W"
    assert state["kyoku_num"] == 1
    assert state["honba"] == 0
    # S4, dealer wins and becomes first >= 30000 -> ends.
    ctx = context(bakaze="S", kyoku=8, oya=3)
    assert _resolve_next_hanchan_state(ctx, result([24000, 25000, 20000, 31000]), {}) is None
    # S4, dealer wins but is not first -> continues (renchan priority).
    ctx = context(bakaze="S", kyoku=8, oya=3)
    state = _resolve_next_hanchan_state(ctx, result([24000, 36000, 20000, 29000]), {})
    assert state["bakaze"] == "S"
    assert state["kyoku_num"] == 4
    assert state["honba"] == ctx["honba"] + 1


def test_next_state_west_round_sudden_death_and_cap() -> None:
    # W1 leader >= 30000 -> ends.
    ctx = context(bakaze="W", kyoku=9, oya=0)
    assert _resolve_next_hanchan_state(ctx, result([31000, 23000, 23000, 23000], outcome="other_tsumo"), {}) is None
    # W1 leader < 30000 -> continues.
    state = _resolve_next_hanchan_state(ctx, result([29000, 23000, 23000, 25000], outcome="other_tsumo"), {})
    assert state["bakaze"] == "W"
    assert state["kyoku_num"] == 2
    # W4 always ends.
    ctx = context(bakaze="W", kyoku=12, oya=3)
    assert _resolve_next_hanchan_state(ctx, result([25000, 25000, 25000, 25000]), {}) is None


def test_next_state_tobi_ends_hanchan() -> None:
    assert _resolve_next_hanchan_state(context(), result([-1000, 40000, 30000, 31000]), {}) is None


def test_summarize_hanchan_aggregates_model_rows() -> None:
    model = FakeModel([0.5, 0.25, 0.15, 0.1])
    rows = [row(1, [30000, 24000, 23000, 23000], outcome="self_win")]
    out = _summarize_hanchan(rows, context(), model)
    assert out["sample"]["games"] == 1
    assert out["expected_rank"]["value"] == pytest.approx(1.85)
    assert out["rank_rates"][0]["count"] == pytest.approx(0.5)
    assert out["rank_rates"][3]["count"] == pytest.approx(0.1)
    assert out["dan_pt_ev"]["houou_7"]["value"] == pytest.approx(
        sum(HANCHAN_PT_TABLES["houou_7"][r] * [0.5, 0.25, 0.15, 0.1][r] for r in range(4))
    )


def test_summarize_hanchan_uses_final_rank_when_hanchan_ends() -> None:
    model = FakeModel([0.5, 0.25, 0.15, 0.1])
    rows = [
        row(1, [30000, 24000, 23000, 23000], outcome="self_win"),
        row(2, [10000, 40000, 25000, 25000], outcome="self_deal_in"),
    ]
    out = _summarize_hanchan(rows, context(bakaze="W", kyoku=12, oya=0), model)
    assert out["sample"]["games"] == 2
    assert out["expected_rank"]["value"] == pytest.approx((1.0 + 4.0) / 2)
    assert out["rank_rates"][0]["count"] == pytest.approx(1.0)
    assert out["rank_rates"][3]["count"] == pytest.approx(1.0)


def test_merge_hanchan_combines_exactly() -> None:
    model = FakeModel([0.5, 0.25, 0.15, 0.1])
    rows = [row(1, [30000, 24000, 23000, 23000], outcome="self_win")]
    left = _summarize_hanchan(rows, context(), model)
    right = _summarize_hanchan(rows, context(), model)
    merged = _merge_hanchan(left, right)
    assert merged["sample"]["games"] == 2
    assert merged["expected_rank"]["n"] == 2
    assert merged["expected_rank"]["value"] == pytest.approx(left["expected_rank"]["value"])
    assert merged["rank_rates"][0]["count"] == pytest.approx(left["rank_rates"][0]["count"] * 2)
    assert merged["dan_pt_ev"]["houou_10"]["n"] == 2

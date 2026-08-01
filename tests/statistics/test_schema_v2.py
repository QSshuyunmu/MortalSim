from __future__ import annotations

from copy import deepcopy

import pytest

from mortal_app.service import OUTCOMES, _compare, _legacy_outcome, _public, _rate, _summarize, _trim_samples, merge_results


class Stat:
    def __getattr__(self, _name: str) -> int:
        return 0


def row(
    outcome: str,
    *,
    method: str | None = None,
    point: int = 0,
    round_balance: int | None = None,
    rank: int = 2,
    seed: int = 1,
    metrics: dict | None = None,
):
    result = {"type": outcome, "outcome": outcome}
    if method:
        result["win_method"] = method
    player = {
        "score_delta": point,
        "round_balance": point if round_balance is None else round_balance,
        "final_rank": rank,
    }
    return {"seed": [seed, 0xDEAD], "trace_hash": f"hash-{seed}", "result": result, "players": [player], "metrics": metrics or {}, "stat": Stat()}


def test_terminal_partition_and_self_win_conservation() -> None:
    rows = [
        row("self_win", method="ron", point=1000, seed=1),
        row("self_win", method="tsumo", point=2000, seed=2),
        row("self_deal_in", point=-1000, seed=3),
        row("draw", seed=4), row("sideways", seed=5), row("other_tsumo", seed=6),
    ]
    candidate = _summarize(rows, 0, "1s")
    outcome = candidate["outcome"]
    assert candidate["completed_games"] == sum(outcome[name]["count"] for name in OUTCOMES)
    assert outcome["self_win"]["count"] == outcome["self_ron"]["count"] + outcome["self_tsumo"]["count"]
    assert outcome["sideways"]["count"] == 1
    assert outcome["other_tsumo"]["count"] == 1


def test_old_hora_is_classified_by_target_perspective() -> None:
    assert _legacy_outcome({"type": "hora", "agari_actor": 2, "agari_target": 1}, 0) == ("sideways", None)
    assert _legacy_outcome({"type": "hora", "agari_actor": 0, "agari_target": 1}, 0) == ("self_win", "ron")
    assert _legacy_outcome({"type": "hora", "agari_actor": 2, "agari_target": 0}, 0) == ("self_deal_in", None)


def test_ci_is_null_for_insufficient_sample() -> None:
    assert _rate(0, 0)["ci95"] is None
    single = _summarize([row("draw")], 0, "1s")
    assert single["value"]["point"]["ci95"] is None


def test_average_round_balance_uses_completed_target_settlements_only() -> None:
    missing_target = {
        "seed": [3, 0xDEAD],
        "trace_hash": "hash-3",
        "result": {"type": "draw", "outcome": "draw"},
        "players": [],
        "metrics": {},
        "stat": Stat(),
    }
    rows = [
        row("self_win", method="ron", point=12_000, seed=1),
        row("self_deal_in", point=-3_000, seed=2),
        missing_target,
        row("error", point=999_999, seed=4),
    ]

    candidate = _summarize(rows, 0, "1s")

    point = candidate["value"]["point"]
    assert candidate["completed_games"] == 2
    assert candidate["errors"] == 2
    assert point["n"] == 2
    assert point["sum"] == 9_000
    assert point["value"] == 4_500
    assert candidate["avg_point"] == 4_500
    assert candidate["special"]["error_types"]["missing_target_score_delta"] == 1


def test_naga_round_balance_is_the_only_public_point_metric() -> None:
    rows = [
        row("self_win", method="ron", point=7_700, round_balance=8_700, seed=1),
        row("draw", point=-1_000, round_balance=0, seed=2),
        row("sideways", point=0, round_balance=0, seed=3),
    ]

    candidate = _summarize(rows, 0, "1m")

    assert candidate["value"]["point"]["value"] == 2_900
    assert candidate["value"]["point_definition"] == "naga_round_balance"
    assert candidate["avg_point"] == 2_900
    assert "net_point" not in candidate["value"]
    assert "avg_net_point" not in candidate
    assert "net_point" not in candidate["samples"]["outcome.self_win"][0]


def test_average_round_balance_rejects_inconsistent_runner_score_delta() -> None:
    inconsistent = row("draw", point=0, seed=1)
    inconsistent["result"].update({
        "initial_scores": [25_000, 25_000, 25_000, 25_000],
        "final_scores": [26_000, 24_000, 25_000, 25_000],
        "score_deltas": [1_000, -1_000, 0, 0],
    })

    candidate = _summarize([inconsistent], 0, "1s")

    assert candidate["completed_games"] == 0
    assert candidate["value"]["point"]["n"] == 0
    assert candidate["special"]["error_types"]["inconsistent_target_score_delta"] == 1


def test_average_round_balance_never_falls_back_to_retired_score_delta() -> None:
    item = row("draw", point=-1_000, seed=1)
    item["players"][0].pop("round_balance")

    candidate = _summarize([item], 0, "1s")

    assert candidate["completed_games"] == 0
    assert candidate["value"]["point"]["n"] == 0
    assert candidate["special"]["error_types"]["missing_round_balance"] == 1


def test_runner_snapshot_enforces_riichi_balance_identity() -> None:
    item = row("self_win", method="ron", point=7_700, round_balance=8_700, seed=1)
    item["players"][0]["riichi_accepted"] = True
    item["result"].update({
        "initial_scores": [25_000, 25_000, 25_000, 25_000],
        "final_scores": [32_700, 17_300, 25_000, 25_000],
        "score_deltas": [7_700, -7_700, 0, 0],
        "round_balances": [8_700, -7_700, 0, 0],
        "kyotaku_start": 0,
        "kyotaku_remaining": 0,
    })

    candidate = _summarize([item], 0, "1m")

    assert candidate["errors"] == 0
    assert candidate["value"]["point"]["value"] == 8_700
    assert "net_point" not in candidate["value"]


def test_paired_comparison_uses_matching_row_order() -> None:
    base = _summarize([row("draw", point=0, seed=1), row("draw", point=100, seed=2)], 0, "1s")
    other = _summarize([row("draw", point=100, seed=1), row("draw", point=300, seed=2)], 0, "6s")
    comparison = _compare(base, other)
    assert comparison["point_delta"]["value"] == 150
    assert comparison["point_delta"]["n"] == 2


def test_first_discard_riichi_has_its_own_candidate_identity() -> None:
    candidate = _summarize([row("draw", seed=1)], 0, "1m", first_riichi=True)

    assert candidate["candidate"] == "riichi:1m"
    assert candidate["first_riichi"] is True
    # This remains the aggregate riichi metric rather than the action flag.
    assert candidate["riichi"]["rate"]["count"] == 0


def test_tenpai_and_draw_tenpai_are_derived_from_rust_metrics() -> None:
    candidate = _summarize([
        row("draw", seed=1, metrics={"first_tenpai_turn": 7, "final_tenpai": True, "fuuro_count": 1}),
        row("draw", seed=2, metrics={"first_tenpai_turn": None, "final_tenpai": False, "fuuro_count": 0}),
    ], 0, "1s")
    assert candidate["tenpai"]["rate"]["count"] == 1
    assert candidate["tenpai"]["average_first_turn"]["value"] == 7
    assert candidate["draw"]["tenpai_count"] == 1
    assert candidate["call"]["average_count"]["value"] == 0.5


def test_representative_samples_are_deterministic_and_capped() -> None:
    rows = [row("sideways", seed=seed) for seed in range(250)]
    first = _summarize(rows, 0, "1s")["samples"]["outcome.sideways"]
    second = _summarize(rows, 0, "1s")["samples"]["outcome.sideways"]
    assert len(first) == 100
    assert first == second


def test_yaku_and_bonus_tiles_are_aggregated_from_rust_metrics() -> None:
    candidate = _summarize([
        row("self_win", method="ron", seed=1, metrics={"version": 1, "yaku_ids": ["riichi", "pinfu"], "han": 3, "raw_win_point": 3900, "dora": 1, "ura_dora": 0, "aka_dora": 0}),
        row("self_win", method="tsumo", seed=2, metrics={"version": 1, "yaku_ids": ["menzen_tsumo"], "han": 4, "raw_win_point": 6000, "dora": 0, "ura_dora": 2, "aka_dora": 1}),
    ], 0, "1s")
    yaku = {item["id"]: item for item in candidate["yaku"]}
    assert yaku["riichi"]["count"] == 1
    assert yaku["dora"]["total_tiles"] == 1
    assert yaku["ura_dora"]["total_tiles"] == 2
    assert candidate["win"]["average_han"]["value"] == 3.5
    assert candidate["win"]["average_raw_point"]["value"] == 4950


def test_extension_merge_matches_one_shot_aggregate() -> None:
    first_rows = [row("sideways", point=seed * 10, rank=(seed % 4) + 1, seed=seed) for seed in range(1, 101)]
    second_rows = [row("sideways", point=-seed * 5, rank=(seed % 4) + 1, seed=seed) for seed in range(101, 201)]
    one_shot = _summarize(first_rows + second_rows, 0, "1s")
    left = _summarize(first_rows, 0, "1s")
    right = _summarize(second_rows, 0, "1s")
    runtime = {
        "engine_id": "aoti-cuda-sm89",
        "artifact_sha256": "runtime-test",
        "build_id": "build-test",
        "compute_capability": "8.9",
        "batch_size": 1000,
        "batch_capacity": 1024,
        "precision_profile": "amp-static-advantage",
    }
    base = {
        "schema_version": 3,
        "metrics_version": 2,
        "decision_contract": "stable_advantage_v2",
        "runtime": runtime,
        "model": {"sha256": "model-test"},
        "runs": 100,
        "total_runs": 100,
        "seed": 1,
        "elapsed": 1.0,
        "candidates": [_public(left)],
        "comparisons": [],
        "extension_history": [],
    }
    extra = {
        "schema_version": 3,
        "metrics_version": 2,
        "decision_contract": "stable_advantage_v2",
        "runtime": runtime,
        "model": {"sha256": "model-test"},
        "runs": 100,
        "total_runs": 100,
        "seed": 101,
        "elapsed": 1.0,
        "candidates": [_public(right)],
        "comparisons": [],
    }
    merged = merge_results(base, extra, "operation")
    candidate = merged["candidates"][0]
    assert candidate["value"]["point"] == one_shot["value"]["point"]
    assert "net_point" not in candidate["value"]
    assert candidate["rank"] == one_shot["rank"]
    assert candidate["outcome"] == one_shot["outcome"]
    assert candidate["samples"] == one_shot["samples"]
    assert candidate["win"]["han_distribution"] == one_shot["win"]["han_distribution"]
    assert candidate["yaku"] == one_shot["yaku"]
    assert candidate["sample"]["seed_start"] == [1, 0xDEAD]
    assert candidate["sample"]["seed_end"] == [200, 0xDEAD]
    assert merged["total_runs"] == 200
    assert merged["extension_history"][0]["seed_start"] == 101


def test_extension_sample_pool_accepts_json_lists_and_live_tuples() -> None:
    """Older persisted runs decode seeds as lists; a live Rust run yields tuples."""
    items = _trim_samples(
        [{"seed": [42, 0xDEAD]}, {"seed": (43, 0xDEAD)}],
        "1s",
        "outcome.draw",
    )
    assert [item["seed"] for item in items] == [[42, 0xDEAD], (43, 0xDEAD)]


def test_schema_v3_merge_rejects_runtime_or_contract_drift() -> None:
    base = {
        "schema_version": 3,
        "metrics_version": 2,
        "decision_contract": "stable_advantage_v2",
        "runtime": {
            "engine_id": "aoti-cuda-sm89",
            "artifact_sha256": "a",
            "build_id": "build",
            "compute_capability": "8.9",
            "batch_size": 1000,
            "batch_capacity": 1024,
            "precision_profile": "amp-static-advantage",
        },
        "model": {"sha256": "model"},
        "candidates": [],
    }
    changed = deepcopy(base)
    changed["runtime"]["artifact_sha256"] = "b"
    with pytest.raises(ValueError, match="artifact_sha256"):
        merge_results(base, changed, "operation")

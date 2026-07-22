from __future__ import annotations

import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
AKAGI_DIR = ROOT / "Akagi"
MORTAL_DIR = ROOT / "mortal"
LIBRIICHI_DIR = ROOT / "target" / "release"
MODEL_PATH = AKAGI_DIR / "model_v4_20240308_best_min.pth"

STAT_FIELDS = (
    "round", "agari", "houjuu", "riichi", "fuuro", "ryukyoku", "point",
)


def _emit(emit: Callable[[dict[str, Any]], None], kind: str, **payload: Any) -> None:
    emit({"type": kind, **payload})


def _prepare_imports(rayon_threads: int) -> None:
    os.environ["RAYON_NUM_THREADS"] = str(rayon_threads)
    sys.path.insert(0, str(MORTAL_DIR))
    sys.path.insert(0, str(LIBRIICHI_DIR))
    sys.path.insert(0, str(AKAGI_DIR))


def _load_engine():
    import torch
    from engine import MortalEngine
    from model import Brain, DQN

    if not MODEL_PATH.exists():
        raise FileNotFoundError(f"模型文件不存在: {MODEL_PATH}")

    state = torch.load(MODEL_PATH, map_location="cpu", weights_only=True)
    cfg = state["config"]
    version = cfg["control"]["version"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    brain = Brain(
        version=version,
        conv_channels=cfg["resnet"]["conv_channels"],
        num_blocks=cfg["resnet"]["num_blocks"],
    ).eval().to(device)
    dqn = DQN(version=version).eval().to(device)
    brain.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])
    engine = MortalEngine(
        brain,
        dqn,
        is_oracle=False,
        version=version,
        device=device,
        enable_amp=device.type == "cuda",
        name="MortalApp",
        enable_rule_based_agari_guard=True,
    )
    return engine, device


def _parse_inputs(request: dict[str, Any]):
    _prepare_imports(int(request.get("rayon_threads", 20)))
    from kyoku_sim_win import parse_hand

    hand = parse_hand(request["hand"])
    if len(hand) != 13:
        raise ValueError(f"手牌必须正好 13 张，当前为 {len(hand)} 张")

    def one_tile(value: str, label: str):
        tiles = parse_hand(value.strip())
        if len(tiles) != 1:
            raise ValueError(f"{label} 必须是单张牌: {value}")
        return tiles[0]

    first_tsumo = one_tile(request["first_tsumo"], "第一摸牌")
    dora = one_tile(request["dora"], "宝牌指示牌")
    raw_discards = request["discards"]
    if isinstance(raw_discards, str):
        raw_discards = raw_discards.split(",")
    discards = [str(v).strip() for v in raw_discards if str(v).strip()]
    if not discards:
        raise ValueError("至少需要一个第一打候选")
    for discard in discards:
        one_tile(discard, "第一打")

    runs = int(request["runs"])
    seed = int(request["seed"])
    oya = int(request["oya"])
    batch_size = int(request["batch_size"])
    rayon_threads = int(request["rayon_threads"])
    if not 1 <= runs <= 100_000:
        raise ValueError("模拟局数必须在 1 到 100000 之间")
    if not 0 <= oya <= 3:
        raise ValueError("亲家座位必须是 0 到 3")
    if batch_size < 1 or rayon_threads < 1:
        raise ValueError("batch size 和 Rayon 线程数必须大于 0")
    return hand, first_tsumo, dora, discards, runs, seed, oya, batch_size, rayon_threads


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _summarize(rows: list[dict[str, Any]], oya: int, discard: str) -> dict[str, Any]:
    counts = {"hora": 0, "tsumo": 0, "ryukyoku": 0, "error": 0}
    ranks = [0, 0, 0, 0]
    points: list[float | None] = []
    stat_sum = {field: 0.0 for field in STAT_FIELDS}
    for row in rows:
        result = row.get("result", {})
        result_type = result.get("type", "error")
        counts[result_type] = counts.get(result_type, 0) + 1
        players = row.get("players", [])
        if len(players) <= oya:
            points.append(None)
            continue
        player = players[oya]
        rank = int(player.get("final_rank", 0) or 0)
        if 1 <= rank <= 4:
            ranks[rank - 1] += 1
        points.append(_number(player.get("score_delta", 0)))
        stat = row.get("stat")
        if stat is not None:
            for field in STAT_FIELDS:
                stat_sum[field] += _number(getattr(stat, field, 0))

    games = len(rows)
    completed = max(games - counts.get("error", 0), 0)
    avg_rank = sum((i + 1) * count for i, count in enumerate(ranks)) / max(completed, 1)
    valid_points = [point for point in points if point is not None]
    avg_point = sum(valid_points) / max(len(valid_points), 1)
    rounds = stat_sum["round"] or completed
    return {
        "discard": discard,
        "games": games,
        "errors": counts.get("error", 0),
        "hora": counts.get("hora", 0),
        "tsumo": counts.get("tsumo", 0),
        "ryukyoku": counts.get("ryukyoku", 0),
        "agari_rate": stat_sum["agari"] / max(rounds, 1),
        "houjuu_rate": stat_sum["houjuu"] / max(rounds, 1),
        "riichi_rate": stat_sum["riichi"] / max(rounds, 1),
        "fuuro_rate": stat_sum["fuuro"] / max(rounds, 1),
        "avg_rank": avg_rank,
        "avg_point": avg_point,
        "rank_counts": ranks,
        "stat": stat_sum,
        "_points": points,
        "_rows": rows,
    }


def _compare(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    paired = [
        b - a
        for a, b in zip(base["_points"], other["_points"])
        if a is not None and b is not None
    ]
    if not paired:
        return {"discard": other["discard"], "paired_point_delta": 0.0, "ci95": [0.0, 0.0]}
    mean = sum(paired) / len(paired)
    variance = sum((value - mean) ** 2 for value in paired) / max(len(paired) - 1, 1)
    stderr = math.sqrt(variance / len(paired))
    return {
        "discard": other["discard"],
        "paired_point_delta": mean,
        "ci95": [mean - 1.96 * stderr, mean + 1.96 * stderr],
        "paired_samples": len(paired),
    }


def run_analysis(request: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    started = time.perf_counter()
    (
        hand, first_tsumo, dora, discards, runs, seed, oya, batch_size, rayon_threads,
    ) = _parse_inputs(request)
    _prepare_imports(rayon_threads)
    _emit(emit, "status", message="正在加载模型")
    engine, device = _load_engine()
    import libriichi

    runner = libriichi.arena.CustomKyokuRunner()
    _emit(emit, "status", message=f"设备: {device}")
    summaries = []
    for candidate_index, discard in enumerate(discards):
        _emit(
            emit,
            "candidate_started",
            discard=discard,
            index=candidate_index,
            total=len(discards),
        )
        rows: list[dict[str, Any]] = []
        for offset in range(0, runs, batch_size):
            count = min(batch_size, runs - offset)
            batch_rows = runner.run_many(
                engine=engine,
                kyoku=1,
                honba=0,
                kyotaku=0,
                bakaze="E",
                oya=oya,
                scores=[25000] * 4,
                dora_marker=request["dora"].strip(),
                main_haipai=hand,
                first_discard=discard,
                first_tsumo=request["first_tsumo"].strip(),
                seed_start=(seed + offset, 0xDEAD),
                count=count,
            )
            rows.extend(batch_rows)
            _emit(
                emit,
                "batch_completed",
                discard=discard,
                completed=min(offset + count, runs),
                total=runs,
            )
        summary = _summarize(rows, oya, discard)
        summaries.append(summary)
        _emit(emit, "candidate_completed", summary=_public_summary(summary))

    comparisons = [_compare(summaries[0], summary) for summary in summaries[1:]]
    return {
        "elapsed": time.perf_counter() - started,
        "device": str(device),
        "runs": runs,
        "seed": seed,
        "summaries": [_public_summary(summary) for summary in summaries],
        "comparisons": comparisons,
    }


def _public_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if not key.startswith("_")}


def worker_main(request: dict[str, Any], event_queue) -> None:
    try:
        result = run_analysis(request, lambda event: event_queue.put(event))
        event_queue.put({"type": "completed", "result": result})
    except BaseException as exc:  # send diagnostics back to the UI process
        event_queue.put({
            "type": "failed",
            "error": str(exc),
            "traceback": traceback.format_exc(),
        })

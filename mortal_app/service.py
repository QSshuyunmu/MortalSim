from __future__ import annotations

import hashlib
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterable

from .model_registry import DEFAULT_MODEL_ID, ModelRegistry


ROOT = Path(__file__).resolve().parents[1]
SIMULATOR_DIR = ROOT / "simulator"
MORTAL_DIR = ROOT / "mortal"
LIBRIICHI_DIR = ROOT / "target" / "release"
MODEL_PATH = ROOT / "models" / "model_v4_20240308_best_min.pth"

OUTCOMES = ("self_win", "self_deal_in", "draw", "sideways", "other_tsumo")
ENGINE_TO_PUBLIC_HONOR = {
    "E": "1z", "S": "2z", "W": "3z", "N": "4z",
    "P": "5z", "F": "6z", "C": "7z",
}
STAT_FIELDS = (
    "game", "round", "oya", "point", "rank_1", "rank_2", "rank_3", "rank_4", "tobi",
    "fuuro", "fuuro_num", "fuuro_point", "fuuro_agari", "fuuro_agari_jun",
    "fuuro_agari_point", "fuuro_houjuu", "agari", "agari_as_oya", "agari_jun",
    "agari_point_oya", "agari_point_ko", "houjuu", "houjuu_jun", "houjuu_to_oya",
    "houjuu_point_to_oya", "houjuu_point_to_ko", "riichi", "riichi_as_oya",
    "riichi_jun", "riichi_agari", "riichi_agari_point", "riichi_agari_jun",
    "riichi_houjuu", "riichi_ryukyoku", "riichi_point", "chasing_riichi",
    "riichi_got_chased", "dama_agari", "dama_agari_jun", "dama_agari_point",
    "ryukyoku", "ryukyoku_point", "yakuman", "nagashi_mangan",
)

# Stable public IDs. Until the Rust scoring result exposes identities, unavailable slots
# remain null rather than being reported as false zeroes.
YAKU_IDS = (
    "riichi", "double_riichi", "ippatsu", "menzen_tsumo", "tanyao", "pinfu",
    "iipeikou", "seat_wind_east", "seat_wind_south", "seat_wind_west", "seat_wind_north",
    "round_wind_east", "round_wind_south", "round_wind_west", "round_wind_north",
    "haku", "hatsu", "chun", "rinshan", "chankan", "haitei", "houtei",
    "sanshoku_doujun", "ikkitsuukan", "chanta", "chiitoitsu", "toitoi", "sanankou",
    "honroutou", "sanshoku_doukou", "sankantsu", "shousangen", "honitsu", "junchan",
    "ryanpeikou", "chinitsu", "kokushi", "suuankou", "daisangen", "shousuushii",
    "daisuushii", "tsuuiisou", "chinroutou", "ryuuiisou", "chuuren", "suukantsu",
    "tenhou", "chiihou", "renhou", "nagashi_mangan", "dora", "ura_dora", "aka_dora",
    "kita", "double_yakuman",
)


def candidate_id(tile: str, riichi: bool = False) -> str:
    """Stable identity for a first action, including its riichi declaration."""
    return f"riichi:{tile}" if riichi else tile


def normalize_candidate(value: Any) -> dict[str, Any]:
    """Accept legacy tile strings and the schema-v2 action object form."""
    if isinstance(value, str):
        tile, riichi = value.strip(), False
    elif isinstance(value, dict):
        tile, riichi = str(value.get("tile", "")).strip(), bool(value.get("riichi", False))
    else:
        raise ValueError("first discard candidate must be a tile string or object")
    if not tile:
        raise ValueError("first discard candidate cannot be empty")
    return {"tile": tile, "riichi": riichi, "candidate": candidate_id(tile, riichi)}


def candidate_identity(value: Any) -> str:
    if isinstance(value, dict) and value.get("candidate"):
        return str(value["candidate"])
    if isinstance(value, dict) and value.get("discard"):
        return candidate_id(str(value["discard"]), bool(value.get("first_riichi", False)))
    return normalize_candidate(value)["candidate"]


def _emit(emit: Callable[[dict[str, Any]], None], kind: str, **payload: Any) -> None:
    emit({"type": kind, **payload})


def _prepare_imports(rayon_threads: int) -> None:
    os.environ["RAYON_NUM_THREADS"] = str(rayon_threads)
    for path in (MORTAL_DIR, LIBRIICHI_DIR, SIMULATOR_DIR):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))


def cuda_diagnostics(engine_name: str = "python") -> dict[str, Any]:
    result: dict[str, Any] = {"available": False, "torch_version": None, "cuda_version": None, "gpu_name": None, "error": None}
    if engine_name == "lite":
        try:
            executable = shutil.which("nvidia-smi")
            if executable:
                probe = subprocess.run(
                    [executable, "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    result.update(available=True, gpu_name=probe.stdout.strip().splitlines()[0])
                    return result
        except (OSError, subprocess.SubprocessError) as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        result["error"] = result["error"] or "NVIDIA driver or nvidia-smi is unavailable"
        return result
    try:
        import torch
        result.update(torch_version=torch.__version__, cuda_version=torch.version.cuda, available=bool(torch.cuda.is_available()))
        if result["available"]:
            result["gpu_name"] = torch.cuda.get_device_name(0)
        elif torch.version.cuda is None:
            result["error"] = "CPU-only PyTorch is installed"
        else:
            result["error"] = "CUDA runtime or NVIDIA driver is unavailable"
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def require_cuda(engine_name: str = "python") -> dict[str, Any]:
    if engine_name == "lite":
        # The Lite build deliberately does not bundle PyTorch.  A driver-level
        # query is enough to provide an early, readable diagnostic; the native
        # runtime performs the definitive CUDA initialization check next.
        try:
            executable = shutil.which("nvidia-smi")
            if executable:
                probe = subprocess.run(
                    [executable, "--query-gpu=name", "--format=csv,noheader"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=False,
                )
                if probe.returncode == 0 and probe.stdout.strip():
                    return {
                        "available": True,
                        "torch_version": None,
                        "cuda_version": None,
                        "gpu_name": probe.stdout.strip().splitlines()[0],
                        "error": None,
                    }
        except (OSError, subprocess.SubprocessError):
            pass
        raise RuntimeError("MortalSim Lite requires an NVIDIA driver; nvidia-smi found no usable GPU")
    status = cuda_diagnostics()
    if not status["available"]:
        raise RuntimeError(f"MortalSim GPU edition requires CUDA; CPU fallback is disabled ({status['error'] or 'CUDA unavailable'}).")
    return status


def _load_engine(model_id: str | None = None, engine_name: str = "python"):
    model = ModelRegistry().get(model_id)
    model_path = Path(model["path"])
    if engine_name == "lite":
        try:
            from mortal.lite_engine import MortalLiteEngine
        except ImportError:
            from lite_engine import MortalLiteEngine

        runtime_dir = Path(
            model.get("lite_runtime_dir")
            or os.environ.get("MORTALSIM_LITE_RUNTIME_DIR", "")
        )
        runtime_path = Path(
            model.get("lite_runtime_path")
            or os.environ.get("MORTALSIM_LITE_RUNTIME", runtime_dir / "mortal_lite_runtime.dll")
        )
        configured_model = model.get("lite_model_path") or os.environ.get("MORTALSIM_LITE_MODEL", "")
        if configured_model:
            lite_model = Path(configured_model)
        else:
            # Portable builds have used both the AOTInductor suffix and the
            # simpler model.dll name.  Resolve either without requiring a
            # per-machine config file.
            candidates = (
                runtime_dir / "mortal-v4-amp-b1024.wrapper.pyd",
                runtime_dir / "mortal-v4-fp32-b256.wrapper.pyd",
                runtime_dir / "model.dll",
            )
            lite_model = next((path for path in candidates if path.is_file()), candidates[0])
        configured_weights = model.get("lite_weights_path") or os.environ.get("MORTALSIM_LITE_WEIGHTS", "")
        lite_weights = Path(configured_weights) if configured_weights else None
        if not all(path.is_file() for path in (runtime_path, lite_model)):
            raise RuntimeError(
                "Mortal Lite runtime is not installed. Set MORTALSIM_LITE_RUNTIME, "
                "MORTALSIM_LITE_MODEL to the portable GPU files."
            )
        checkpoint_path = model_path if lite_weights is None or lite_weights.suffix.lower() == ".pth" else None
        if lite_weights is not None and not lite_weights.is_file():
            raise RuntimeError(f"Mortal Lite weight blob is missing: {lite_weights}")
        require_cuda("lite")
        capacity = int(model.get("lite_batch_capacity") or os.environ.get("MORTALSIM_LITE_BATCH_CAPACITY", "1024"))
        for marker, marker_capacity in (("-b256", 256), ("-b512", 512), ("-b1024", 1024)):
            if marker in lite_model.name.lower() and not model.get("lite_batch_capacity") and not os.environ.get("MORTALSIM_LITE_BATCH_CAPACITY"):
                capacity = marker_capacity
                break
        return MortalLiteEngine(
            runtime_path,
            lite_model,
            lite_weights if checkpoint_path is None else None,
            checkpoint_path=checkpoint_path,
            capacity=capacity,
            name="Mortal Lite",
        ), "cuda:0", {**model, "engine": "mortal-lite"}

    import torch
    from engine import MortalEngine
    from model import Brain, DQN
    require_cuda()
    state = torch.load(model_path, map_location="cpu", weights_only=True)
    cfg = state["config"]
    version = cfg["control"]["version"]
    device = torch.device("cuda")
    brain = Brain(version=version, conv_channels=cfg["resnet"]["conv_channels"], num_blocks=cfg["resnet"]["num_blocks"]).eval().to(device)
    dqn = DQN(version=version).eval().to(device)
    brain.load_state_dict(state["mortal"])
    dqn.load_state_dict(state["current_dqn"])
    return MortalEngine(brain, dqn, is_oracle=False, version=version, device=device, enable_amp=True, name="MortalApp", enable_rule_based_agari_guard=True), device, model


def resolve_simulation_context(request: dict[str, Any]) -> dict[str, Any]:
    """Resolve public relative-seat inputs to libriichi's absolute seats."""
    if "round" not in request:
        # Historical schema-v2 requests used an explicit dealer seat while
        # always simulating an East round. Preserve that replay behavior.
        oya = int(request.get("oya", 0))
        return {
            "round": f"E{oya + 1}",
            "kyoku": 1,
            "bakaze": "E",
            "oya": oya,
            "honba": int(request.get("honba", 0)),
            "kyotaku": int(request.get("kyotaku", 0)),
            "scores": [int(value) for value in request.get("absolute_scores", [25_000] * 4)],
        }

    round_id = str(request["round"]).upper()
    if len(round_id) != 2 or round_id[0] not in "ESW" or round_id[1] not in "1234":
        raise ValueError(f"invalid round: {round_id}")
    wind_index = "ESW".index(round_id[0])
    round_number = int(round_id[1])
    kyoku = wind_index * 4 + round_number
    oya = round_number - 1
    honba = int(request.get("honba", 0))
    kyotaku = int(request.get("kyotaku", 0))
    relative = request.get("scores") or {}
    values = (
        int(relative.get("self", 25_000)),
        int(relative.get("shimocha", 25_000)),
        int(relative.get("toimen", 25_000)),
    )
    kamicha = 100_000 - kyotaku * 1_000 - sum(values)
    all_relative = (*values, kamicha)
    if not 0 <= honba <= 99 or not 0 <= kyotaku <= 99:
        raise ValueError("honba and kyotaku must be between 0 and 99")
    if any(value < 0 or value % 100 for value in all_relative):
        raise ValueError("all scores must be non-negative multiples of 100")
    scores = [0] * 4
    for offset, value in enumerate(all_relative):
        scores[(oya + offset) % 4] = value
    return {
        "round": round_id,
        "kyoku": kyoku,
        "bakaze": round_id[0],
        "oya": oya,
        "honba": honba,
        "kyotaku": kyotaku,
        "scores": scores,
        "relative_scores": {
            "self": values[0],
            "shimocha": values[1],
            "toimen": values[2],
            "kamicha": kamicha,
        },
    }


def _parse_inputs(request: dict[str, Any]):
    _prepare_imports(int(request.get("rayon_threads", 20)))
    from kyoku_sim_win import parse_hand
    complete_hand = parse_hand(request["hand"])

    def one_tile(value: str, label: str):
        tiles = parse_hand(value.strip())
        if len(tiles) != 1:
            raise ValueError(f"{label}必须是单张牌: {value}")
        return tiles[0]

    legacy_first_tsumo = request.get("first_tsumo")
    if legacy_first_tsumo is None:
        if len(complete_hand) != 14:
            raise ValueError(f"手牌（含最后一张第一摸）必须正好 14 张，当前为 {len(complete_hand)} 张")
        hand, first_tsumo = complete_hand[:-1], complete_hand[-1]
    else:
        # Schema v2 histories stored the 13-tile hand and first tsumo
        # separately.  Preserve their exact replay semantics indefinitely.
        if len(complete_hand) != 13:
            raise ValueError(f"旧版手牌必须正好 13 张，当前为 {len(complete_hand)} 张")
        hand, first_tsumo = complete_hand, one_tile(str(legacy_first_tsumo), "第一摸牌")
    dora = one_tile(request["dora"], "宝牌指示牌")
    raw_discards = request["discards"]
    if isinstance(raw_discards, str):
        raw_discards = raw_discards.split(",")
    discards = [normalize_candidate(value) for value in raw_discards]
    if not discards:
        raise ValueError("至少需要一个第一打候选")
    for candidate in discards:
        # Compact notation such as ``1z`` is the public/UI form, while the
        # Rust API expects its canonical honor names (``E`` here). Preserve
        # the compact form for IDs, history, and tile rendering.
        engine_tile = one_tile(candidate["tile"], "第一打")
        candidate["tile"] = ENGINE_TO_PUBLIC_HONOR.get(engine_tile, engine_tile)
        candidate["engine_tile"] = engine_tile
        candidate["candidate"] = candidate_id(candidate["tile"], candidate["riichi"])
    if len({candidate["candidate"] for candidate in discards}) != len(discards):
        raise ValueError("第一打候选不能重复")
    runs, seed = int(request["runs"]), int(request["seed"])
    batch_size, rayon_threads = int(request["batch_size"]), int(request["rayon_threads"])
    context = resolve_simulation_context(request)
    if not 1 <= runs <= 100_000 or batch_size < 1 or rayon_threads < 1:
        raise ValueError("模拟参数超出允许范围")
    return hand, first_tsumo, dora, discards, runs, seed, context, batch_size, rayon_threads


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _t_critical(df: int) -> float:
    table = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042, 60: 2.000}
    return next((table[k] for k in sorted(table) if df <= k), 1.96)


def _mean(values: Iterable[float]) -> dict[str, Any]:
    data = [float(value) for value in values]
    total = math.fsum(data)
    total_sq = math.fsum(value * value for value in data)
    if not data:
        return {"value": None, "stddev": None, "ci95": None, "n": 0, "sum": 0.0, "sum_sq": 0.0}
    value = total / len(data)
    if len(data) < 2:
        return {"value": value, "stddev": None, "ci95": None, "n": len(data), "sum": total, "sum_sq": total_sq}
    variance = max(0.0, (total_sq - total * total / len(data)) / (len(data) - 1))
    stddev = math.sqrt(variance)
    margin = _t_critical(len(data) - 1) * stddev / math.sqrt(len(data))
    return {"value": value, "stddev": stddev, "ci95": [value - margin, value + margin], "n": len(data), "sum": total, "sum_sq": total_sq}


def _rate(count: int, total: int) -> dict[str, Any]:
    if total <= 0:
        return {"count": count, "total": total, "rate": None, "ci95": None}
    p, z, z2 = count / total, 1.959963984540054, 1.959963984540054**2
    center = (p + z2 / (2 * total)) / (1 + z2 / total)
    margin = z * math.sqrt((p * (1 - p) + z2 / (4 * total)) / total) / (1 + z2 / total)
    return {"count": count, "total": total, "rate": p, "ci95": [max(0.0, center - margin), min(1.0, center + margin)]}


def _ratio(count: float, total: float) -> dict[str, Any]:
    return _rate(int(count), int(total))


def _legacy_outcome(result: dict[str, Any], oya: int) -> tuple[str, str | None]:
    outcome = result.get("outcome") or result.get("type")
    if outcome in OUTCOMES or outcome == "error":
        return outcome, result.get("win_method")
    actor, target = result.get("agari_actor"), result.get("agari_target")
    if outcome == "tsumo":
        return ("self_win", "tsumo") if actor == oya else ("other_tsumo", None)
    if outcome == "hora":
        if actor == oya:
            return "self_win", "ron"
        if target == oya:
            return "self_deal_in", None
        return "sideways", None
    if outcome == "ryukyoku":
        return "draw", None
    return "error", None


def _target_player(row: dict[str, Any], oya: int) -> tuple[dict[str, Any] | None, str | None]:
    """Validate target settlement balance and exact end-minus-start score delta."""
    players = row.get("players")
    if not isinstance(players, list) or len(players) <= oya:
        return None, "missing_target_score_delta"
    player = players[oya]
    if not isinstance(player, dict) or "score_delta" not in player:
        return None, "missing_target_score_delta"
    try:
        score_delta = float(player["score_delta"])
    except (TypeError, ValueError):
        return None, "invalid_target_score_delta"
    if not math.isfinite(score_delta):
        return None, "invalid_target_score_delta"

    if "round_balance" not in player:
        return None, "missing_round_balance"
    try:
        round_balance = float(player["round_balance"])
    except (TypeError, ValueError):
        return None, "invalid_round_balance"
    if not math.isfinite(round_balance):
        return None, "invalid_round_balance"

    # New runner rows include both score snapshots and the terminal settlement
    # vector used by NAGA's round-balance convention. The latter excludes the
    # 1,000-point payment made when the target's riichi is accepted.
    result = row.get("result")
    if isinstance(result, dict) and "initial_scores" in result:
        try:
            initial = [float(value) for value in result["initial_scores"]]
            final = [float(value) for value in result["final_scores"]]
            deltas = [float(value) for value in result["score_deltas"]]
        except (KeyError, TypeError, ValueError):
            return None, "invalid_score_snapshot"
        if len(initial) != 4 or len(final) != 4 or len(deltas) != 4:
            return None, "invalid_score_snapshot"
        if not all(math.isfinite(value) for value in (*initial, *final, *deltas)):
            return None, "invalid_score_snapshot"
        if final[oya] - initial[oya] != score_delta or deltas[oya] != score_delta:
            return None, "inconsistent_target_score_delta"
        if any(final[index] - initial[index] != deltas[index] for index in range(4)):
            return None, "inconsistent_score_deltas"
        if "kyotaku_start" in result and "kyotaku_remaining" in result:
            try:
                expected_total = 1_000 * (int(result["kyotaku_start"]) - int(result["kyotaku_remaining"]))
            except (TypeError, ValueError):
                return None, "invalid_kyotaku_snapshot"
            if sum(deltas) != expected_total:
                return None, "inconsistent_kyotaku_balance"
        if "round_balances" in result:
            try:
                round_balances = [float(value) for value in result["round_balances"]]
                round_balance = float(player["round_balance"])
            except (KeyError, TypeError, ValueError):
                return None, "invalid_round_balance"
            if len(round_balances) != 4 or not all(math.isfinite(value) for value in round_balances):
                return None, "invalid_round_balance"
            if round_balances[oya] != round_balance:
                return None, "inconsistent_round_balance"
            accepted = bool(player.get("riichi_accepted", False))
            if round_balance - score_delta != (1_000 if accepted else 0):
                return None, "inconsistent_riichi_balance"

    validated = dict(player)
    validated["score_delta"] = score_delta
    validated["round_balance"] = round_balance
    return validated, None


def _sample(rows: list[dict[str, Any]], discard: str, oya: int) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        outcome, method = _legacy_outcome(row.get("result", {}), oya)
        player, player_error = _target_player(row, oya)
        if outcome != "error" and player_error:
            outcome, method = "error", None
        player = player or {}
        item = {
            "seed": row.get("seed"),
            "trace_hash": row.get("trace_hash"),
            "point": player.get("round_balance"),
            "rank": player.get("final_rank"),
            "outcome": outcome,
            "win_method": method,
            "candidate": discard,
        }
        metric_names: list[str | None] = [
            f"outcome.{outcome}",
            f"win_method.{method}" if method else None,
        ]
        metrics = row.get("metrics", {})
        metric_names.extend(f"yaku.{yaku_id}" for yaku_id in metrics.get("yaku_ids", []))
        metric_names.extend(
            f"yaku.{bonus_id}"
            for bonus_id in ("dora", "ura_dora", "aka_dora")
            if int(metrics.get(bonus_id, 0) or 0) > 0
        )
        for metric in metric_names:
            if metric:
                buckets.setdefault(metric, []).append(item)
    for metric, items in list(buckets.items()):
        buckets[metric] = _trim_samples(items, discard, metric)
    return buckets


def _summarize(
    rows: list[dict[str, Any]],
    oya: int,
    discard: str,
    elapsed: float = 0.0,
    *,
    first_riichi: bool = False,
) -> dict[str, Any]:
    outcome_counts = {name: 0 for name in OUTCOMES}
    methods = {"ron": 0, "tsumo": 0}
    ranks = [0, 0, 0, 0]
    points: list[float | None] = []
    rank_samples: list[float] = []
    stat_sum = {field: 0.0 for field in STAT_FIELDS}
    error_types: dict[str, int] = {}
    indicators: dict[str, list[float | None]] = {name: [] for name in OUTCOMES}
    first_tenpai_turns: list[float] = []
    tenpai_games = 0
    draw_tenpai_games = 0
    fuuro_counts: list[float] = []
    raw_win_points: list[float] = []
    win_hans: list[float] = []
    win_fus: list[float] = []
    han_counts: dict[str, int] = {}
    yaku_counts = {yaku_id: 0 for yaku_id in YAKU_IDS}
    bonus_tiles = {"dora": 0, "ura_dora": 0, "aka_dora": 0}
    detailed_wins = 0
    has_game_metrics = False
    for row in rows:
        result = row.get("result", {})
        outcome, method = _legacy_outcome(result, oya)
        player, player_error = _target_player(row, oya)
        if outcome != "error" and player_error:
            outcome, method = "error", None
        for name in OUTCOMES:
            indicators[name].append(1.0 if outcome == name else (None if outcome == "error" else 0.0))
        if outcome == "error":
            key = player_error or str(result.get("error") or "runner_error")
            error_types[key] = error_types.get(key, 0) + 1
            points.append(None)
            continue
        outcome_counts[outcome] += 1
        if method in methods:
            methods[method] += 1
        assert player is not None
        rank = int(player.get("final_rank", 0) or 0)
        if 1 <= rank <= 4:
            ranks[rank - 1] += 1
            rank_samples.append(float(rank))
        points.append(_number(player["round_balance"]))
        metrics = row.get("metrics", {})
        has_game_metrics = has_game_metrics or int(metrics.get("version", 0) or 0) >= 1
        first_tenpai_turn = metrics.get("first_tenpai_turn")
        if first_tenpai_turn is not None:
            first_tenpai_turns.append(_number(first_tenpai_turn))
            tenpai_games += 1
        if outcome == "draw" and metrics.get("final_tenpai"):
            draw_tenpai_games += 1
        fuuro_counts.append(_number(metrics.get("fuuro_count", 0)))
        if outcome == "self_win" and metrics.get("yaku_ids") is not None:
            detailed_wins += 1
            for yaku_id in set(metrics.get("yaku_ids", [])):
                if yaku_id in yaku_counts:
                    yaku_counts[yaku_id] += 1
            for bonus_id in bonus_tiles:
                count = int(metrics.get(bonus_id, 0) or 0)
                bonus_tiles[bonus_id] += count
                if count > 0:
                    yaku_counts[bonus_id] += 1
            if metrics.get("raw_win_point") is not None:
                raw_win_points.append(_number(metrics["raw_win_point"]))
            if metrics.get("han") is not None:
                han = int(metrics["han"])
                win_hans.append(float(han))
                han_counts[str(han)] = han_counts.get(str(han), 0) + 1
            if metrics.get("fu") is not None:
                win_fus.append(_number(metrics["fu"]))
        stat = row.get("stat")
        if stat is not None:
            for field in STAT_FIELDS:
                stat_sum[field] += _number(getattr(stat, field, 0))

    games, errors = len(rows), sum(error_types.values())
    completed = games - errors
    assert completed == sum(outcome_counts.values())
    assert outcome_counts["self_win"] == methods["ron"] + methods["tsumo"]
    point_stats = _mean(point for point in points if point is not None)
    rank_stats = _mean(rank_samples)
    valid_point_sequence = [point for point in points if point is not None]
    stability: list[dict[str, float | int]] = []
    running_total = 0.0
    stride = max(1, math.ceil(len(valid_point_sequence) / 100))
    for index, point in enumerate(valid_point_sequence, 1):
        running_total += point
        if index % stride == 0 or index == len(valid_point_sequence):
            stability.append({"games": index, "average_point": running_total / index})
    wins, riichi_count, fuuro, dama = stat_sum["agari"], stat_sum["riichi"], stat_sum["fuuro"], stat_sum["dama_agari"]
    agari_points = stat_sum["agari_point_oya"] + stat_sum["agari_point_ko"]
    houjuu_points = stat_sum["houjuu_point_to_oya"] + stat_sum["houjuu_point_to_ko"]
    seeds = [row.get("seed") for row in rows if row.get("seed") is not None]
    seed_key = lambda value: tuple(value) if isinstance(value, (list, tuple)) else (value,)
    candidate = {
        "candidate": candidate_id(discard, first_riichi),
        "discard": discard,
        "first_riichi": first_riichi,
        "sample": {
            "games": games,
            "completed_games": completed,
            "errors": errors,
            "seed_start": min(seeds, key=seed_key) if seeds else None,
            "seed_end": max(seeds, key=seed_key) if seeds else None,
            "elapsed_seconds": elapsed,
            "games_per_second": completed / elapsed if elapsed else None,
        },
        "value": {
            "point": point_stats,
            "rank": rank_stats,
            "point_definition": "naga_round_balance",
        },
        "rank": {"average": rank_stats, "positions": [_rate(count, completed) for count in ranks]},
        "outcome": {**{name: _rate(count, completed) for name, count in outcome_counts.items()}, "self_ron": _rate(methods["ron"], completed), "self_tsumo": _rate(methods["tsumo"], completed)},
        "win": {
            "rate": _rate(outcome_counts["self_win"], completed), "ron_share": _rate(methods["ron"], outcome_counts["self_win"]), "tsumo_share": _rate(methods["tsumo"], outcome_counts["self_win"]),
            "riichi_share": _ratio(stat_sum["riichi_agari"], wins), "open_share": _ratio(stat_sum["fuuro_agari"], wins), "dama_share": _ratio(dama, wins),
            "average_point": agari_points / wins if wins else None, "average_raw_point": _mean(raw_win_points), "average_han": _mean(win_hans), "average_fu": _mean(win_fus), "han_distribution": han_counts if detailed_wins else None,
        },
        "defense": {"deal_in_rate": _rate(outcome_counts["self_deal_in"], completed), "other_tsumo_rate": _rate(outcome_counts["other_tsumo"], completed), "sideways_rate": _rate(outcome_counts["sideways"], completed), "average_deal_in_loss": houjuu_points / stat_sum["houjuu"] if stat_sum["houjuu"] else None, "average_deal_in_turn": stat_sum["houjuu_jun"] / stat_sum["houjuu"] if stat_sum["houjuu"] else None},
        "riichi": {"rate": _ratio(riichi_count, completed), "first_rate": _ratio(riichi_count - stat_sum["chasing_riichi"], riichi_count), "chase_rate": _ratio(stat_sum["chasing_riichi"], riichi_count), "win_after_rate": _ratio(stat_sum["riichi_agari"], riichi_count), "average_turn": stat_sum["riichi_jun"] / riichi_count if riichi_count else None},
        "tenpai": {"rate": _rate(tenpai_games, completed), "average_first_turn": _mean(first_tenpai_turns), "draw_tenpai_rate": _rate(draw_tenpai_games, outcome_counts["draw"])},
        "call": {"rate": _ratio(fuuro, completed), "average_count": _mean(fuuro_counts), "win_after_rate": _ratio(stat_sum["fuuro_agari"], fuuro), "average_balance": stat_sum["fuuro_point"] / fuuro if fuuro else None},
        "draw": {"rate": _rate(outcome_counts["draw"], completed), "average_balance": stat_sum["ryukyoku_point"] / stat_sum["ryukyoku"] if stat_sum["ryukyoku"] else None, "tenpai_count": draw_tenpai_games},
        "special": {"yakuman": int(stat_sum["yakuman"]), "nagashi_mangan": int(stat_sum["nagashi_mangan"]), "error_types": error_types},
        "yaku": [{"id": yaku_id, "count": yaku_counts[yaku_id] if has_game_metrics else None, "rate": yaku_counts[yaku_id] / wins if has_game_metrics and wins else (0.0 if has_game_metrics else None), "total_tiles": bonus_tiles[yaku_id] if has_game_metrics and yaku_id in bonus_tiles else None, "available": has_game_metrics} for yaku_id in YAKU_IDS],
        "samples": _sample(rows, candidate_id(discard, first_riichi), oya),
        "stability": stability,
        "replay_events": next((row.get("trace_events") for row in rows if row.get("trace_events")), None),
        # Flat compatibility fields for old clients.
        "games": games, "completed_games": completed, "errors": errors,
        "avg_point": point_stats["value"], "point_ci95": point_stats["ci95"],
        "avg_rank": rank_stats["value"], "rank_counts": ranks,
        "agari_rate": outcome_counts["self_win"] / completed if completed else None, "houjuu_rate": outcome_counts["self_deal_in"] / completed if completed else None, "riichi_rate": riichi_count / completed if completed else None, "fuuro_rate": fuuro / completed if completed else None,
        "_points": points, "_indicators": indicators,
    }
    return candidate


def _compare(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    def paired(left: list[float | None], right: list[float | None]) -> dict[str, Any]:
        return _mean(b - a for a, b in zip(left, right) if a is not None and b is not None)
    return {
        "reference": base.get("candidate", base["discard"]),
        "candidate": other.get("candidate", other["discard"]),
        "point_delta": paired(base["_points"], other["_points"]),
        "outcome_deltas": {
            name: paired(base["_indicators"][name], other["_indicators"][name])
            for name in OUTCOMES
        },
    }


def _merge_mean(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    left, right = left or {}, right or {}
    n1, n2 = int(left.get("n", 0) or 0), int(right.get("n", 0) or 0)
    if not n1:
        return deepcopy(right)
    if not n2:
        return deepcopy(left)
    m1, m2 = float(left["value"]), float(right["value"])
    sum1 = float(left.get("sum", m1 * n1))
    sum2 = float(right.get("sum", m2 * n2))
    sum_sq1 = left.get("sum_sq")
    sum_sq2 = right.get("sum_sq")
    if sum_sq1 is None:
        variance1 = float(left.get("stddev") or 0.0) ** 2
        sum_sq1 = variance1 * max(0, n1 - 1) + sum1 * sum1 / n1
    if sum_sq2 is None:
        variance2 = float(right.get("stddev") or 0.0) ** 2
        sum_sq2 = variance2 * max(0, n2 - 1) + sum2 * sum2 / n2
    n = n1 + n2
    total = sum1 + sum2
    total_sq = float(sum_sq1) + float(sum_sq2)
    mean = total / n
    if n < 2:
        return {"value": mean, "stddev": None, "ci95": None, "n": n, "sum": total, "sum_sq": total_sq}
    stddev = math.sqrt(max(0.0, (total_sq - total * total / n) / (n - 1)))
    margin = _t_critical(n - 1) * stddev / math.sqrt(n)
    return {"value": mean, "stddev": stddev, "ci95": [mean - margin, mean + margin], "n": n, "sum": total, "sum_sq": total_sq}


def _merge_rate(left: dict[str, Any] | None, right: dict[str, Any] | None) -> dict[str, Any]:
    left, right = left or {}, right or {}
    return _rate(
        int(left.get("count", 0) or 0) + int(right.get("count", 0) or 0),
        int(left.get("total", 0) or 0) + int(right.get("total", 0) or 0),
    )


def _weighted(left: Any, left_n: int, right: Any, right_n: int) -> float | None:
    values = [(float(value), count) for value, count in ((left, left_n), (right, right_n)) if value is not None and count > 0]
    total = sum(count for _, count in values)
    return sum(value * count for value, count in values) / total if total else None


def _trim_samples(samples: list[dict[str, Any]], discard: str, metric: str) -> list[dict[str, Any]]:
    def seed_order(item: dict[str, Any]) -> tuple[int, ...]:
        value = item.get("seed")
        if isinstance(value, (list, tuple)):
            return tuple(int(part) for part in value)
        return (int(value),)

    # Persisted JSON turns Rust seed tuples into lists. Normalize both forms so
    # extending an older run cannot compare a tuple with an integer while
    # sorting or accidentally retain the same seed twice.
    unique = {seed_order(item): item for item in samples}
    items = list(unique.values())
    if len(items) <= 100:
        return sorted(items, key=seed_order)
    ordered = sorted(items, key=seed_order)
    head = ordered[:50]
    rest = ordered[50:]
    rest.sort(key=lambda item: hashlib.sha256(f"{discard}:{metric}:{seed_order(item)}".encode()).digest())
    return head + rest[:50]


def merge_results(base: dict[str, Any], extra: dict[str, Any], operation_id: str) -> dict[str, Any]:
    """Merge a completed extension into a schema-v2 result."""
    merged = deepcopy(base)
    extra_by_discard = {candidate_identity(item): item for item in extra.get("candidates", [])}
    candidates: list[dict[str, Any]] = []
    for left in base.get("candidates", []):
        right = extra_by_discard[candidate_identity(left)]
        out = deepcopy(left)
        games = int(left.get("games", 0)) + int(right.get("games", 0))
        completed = int(left.get("completed_games", 0)) + int(right.get("completed_games", 0))
        errors = int(left.get("errors", 0)) + int(right.get("errors", 0))
        out["games"], out["completed_games"], out["errors"] = games, completed, errors
        out["value"] = {
            "point": _merge_mean(left["value"]["point"], right["value"]["point"]),
            "rank": _merge_mean(left["value"]["rank"], right["value"]["rank"]),
            "point_definition": "naga_round_balance",
        }
        out["avg_point"] = out["value"]["point"]["value"]
        out["point_ci95"] = out["value"]["point"]["ci95"]
        out["avg_rank"] = out["value"]["rank"]["value"]
        out["rank"] = {
            "average": out["value"]["rank"],
            "positions": [_merge_rate(a, b) for a, b in zip(left["rank"]["positions"], right["rank"]["positions"])],
        }
        out["rank_counts"] = [item["count"] for item in out["rank"]["positions"]]
        out["outcome"] = {key: _merge_rate(left["outcome"].get(key), right["outcome"].get(key)) for key in left["outcome"]}
        for section in ("win", "defense", "riichi", "tenpai", "call", "draw"):
            out[section] = deepcopy(left[section])
            for key, value in right[section].items():
                if isinstance(value, dict) and "count" in value:
                    out[section][key] = _merge_rate(left[section].get(key), value)
                elif isinstance(value, dict) and "n" in value:
                    out[section][key] = _merge_mean(left[section].get(key), value)
        wins1, wins2 = left["outcome"]["self_win"]["count"], right["outcome"]["self_win"]["count"]
        deal1, deal2 = left["outcome"]["self_deal_in"]["count"], right["outcome"]["self_deal_in"]["count"]
        draw1, draw2 = left["outcome"]["draw"]["count"], right["outcome"]["draw"]["count"]
        riichi1, riichi2 = left["riichi"]["rate"]["count"], right["riichi"]["rate"]["count"]
        call1, call2 = left["call"]["rate"]["count"], right["call"]["rate"]["count"]
        out["win"]["average_point"] = _weighted(left["win"].get("average_point"), wins1, right["win"].get("average_point"), wins2)
        out["defense"]["average_deal_in_loss"] = _weighted(left["defense"].get("average_deal_in_loss"), deal1, right["defense"].get("average_deal_in_loss"), deal2)
        out["defense"]["average_deal_in_turn"] = _weighted(left["defense"].get("average_deal_in_turn"), deal1, right["defense"].get("average_deal_in_turn"), deal2)
        out["riichi"]["average_turn"] = _weighted(left["riichi"].get("average_turn"), riichi1, right["riichi"].get("average_turn"), riichi2)
        out["call"]["average_balance"] = _weighted(left["call"].get("average_balance"), call1, right["call"].get("average_balance"), call2)
        out["draw"]["average_balance"] = _weighted(left["draw"].get("average_balance"), draw1, right["draw"].get("average_balance"), draw2)
        out["draw"]["tenpai_count"] = int(left["draw"].get("tenpai_count", 0) or 0) + int(right["draw"].get("tenpai_count", 0) or 0)
        out["win"]["han_distribution"] = deepcopy(left["win"].get("han_distribution") or {})
        for key, count in (right["win"].get("han_distribution") or {}).items():
            out["win"]["han_distribution"][key] = out["win"]["han_distribution"].get(key, 0) + count
        out["special"] = {
            "yakuman": int(left["special"].get("yakuman", 0)) + int(right["special"].get("yakuman", 0)),
            "nagashi_mangan": int(left["special"].get("nagashi_mangan", 0)) + int(right["special"].get("nagashi_mangan", 0)),
            "error_types": deepcopy(left["special"].get("error_types", {})),
        }
        for key, count in right["special"].get("error_types", {}).items():
            out["special"]["error_types"][key] = out["special"]["error_types"].get(key, 0) + count
        right_yaku = {item["id"]: item for item in right.get("yaku", [])}
        out["yaku"] = []
        for item in left.get("yaku", []):
            other = right_yaku.get(item["id"], {})
            count = (item.get("count") or 0) + (other.get("count") or 0)
            total_tiles = None if item.get("total_tiles") is None and other.get("total_tiles") is None else (item.get("total_tiles") or 0) + (other.get("total_tiles") or 0)
            out["yaku"].append({**item, "count": count, "rate": count / (wins1 + wins2) if wins1 + wins2 else 0.0, "total_tiles": total_tiles})
        out["samples"] = {}
        for metric in set(left.get("samples", {})) | set(right.get("samples", {})):
            out["samples"][metric] = _trim_samples(
                left.get("samples", {}).get(metric, []) + right.get("samples", {}).get(metric, []),
                candidate_identity(left),
                metric,
            )
        base_sum = float(left["value"]["point"].get("value") or 0) * int(left["value"]["point"].get("n", 0))
        out["stability"] = deepcopy(left.get("stability", []))
        for point in right.get("stability", []):
            child_games = int(point["games"])
            total_games = int(left["value"]["point"].get("n", 0)) + child_games
            out["stability"].append({"games": total_games, "average_point": (base_sum + float(point["average_point"]) * child_games) / total_games})
        sample = out["sample"] = deepcopy(left.get("sample", {}))
        sample["games"], sample["completed_games"], sample["errors"] = games, completed, errors
        sample["seed_end"] = right.get("sample", {}).get("seed_end")
        sample["elapsed_seconds"] = float(left.get("sample", {}).get("elapsed_seconds", 0)) + float(right.get("sample", {}).get("elapsed_seconds", 0))
        sample["games_per_second"] = completed / sample["elapsed_seconds"] if sample["elapsed_seconds"] else None
        out["agari_rate"] = out["outcome"]["self_win"]["rate"]
        out["houjuu_rate"] = out["outcome"]["self_deal_in"]["rate"]
        out["riichi_rate"] = out["riichi"]["rate"]["rate"]
        out["fuuro_rate"] = out["call"]["rate"]["rate"]
        candidates.append(out)
    merged["candidates"] = candidates
    extra_comparisons = {(item["reference"], item["candidate"]): item for item in extra.get("comparisons", [])}
    merged["comparisons"] = []
    for item in base.get("comparisons", []):
        other = extra_comparisons[(item["reference"], item["candidate"])]
        merged["comparisons"].append({
            **item,
            "point_delta": _merge_mean(item["point_delta"], other["point_delta"]),
            "outcome_deltas": {key: _merge_mean(item["outcome_deltas"][key], other["outcome_deltas"][key]) for key in item["outcome_deltas"]},
        })
    additional = int(extra.get("runs", 0))
    merged["runs"] = int(base.get("runs", 0)) + additional
    merged["total_runs"] = merged["runs"]
    merged["elapsed"] = float(base.get("elapsed", 0)) + float(extra.get("elapsed", 0))
    merged["merge_state_version"] = 1
    history = list(base.get("extension_history", []))
    history.append({
        "operation_id": operation_id,
        "additional_runs": additional,
        "seed_start": extra.get("seed"),
        "seed_end": extra.get("seed", 0) + additional - 1,
        "elapsed": extra.get("elapsed"),
        "batch_size": (extra.get("config") or {}).get("batch_size"),
        "model_id": (extra.get("model") or {}).get("id"),
        "model_sha256": (extra.get("model") or {}).get("sha256"),
    })
    merged["extension_history"] = history
    return merged


def _public(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if not key.startswith("_")}


def run_analysis(request: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    started = time.perf_counter()
    # Representative samples and deterministic replay require a per-game trace
    # identity. The Rust runner hashes the already-buffered event list and does
    # not persist the full log.
    os.environ["MORTAL_TRACE"] = "1"
    if request.get("replay_of"):
        os.environ["MORTAL_TRACE_EVENTS"] = "1"
    else:
        os.environ.pop("MORTAL_TRACE_EVENTS", None)
    hand, first_tsumo, dora, discards, runs, seed, context, batch_size, rayon_threads = _parse_inputs(request)
    oya = int(context["oya"])
    _prepare_imports(rayon_threads)
    _emit(emit, "status", message="正在加载模型")
    engine, device, model = _load_engine(
        request.get("model_id", DEFAULT_MODEL_ID), request.get("engine", "python")
    )
    import libriichi
    runner = libriichi.arena.CustomKyokuRunner()
    _emit(emit, "status", message=f"设备: {device}")
    candidates = []
    for index, first_action in enumerate(discards):
        discard = first_action["tile"]
        engine_discard = first_action["engine_tile"]
        first_riichi = first_action["riichi"]
        action_id = first_action["candidate"]
        candidate_started = time.perf_counter()
        _emit(emit, "candidate_started", discard=discard, candidate=action_id, riichi=first_riichi, index=index, total=len(discards))
        rows: list[dict[str, Any]] = []
        for offset in range(0, runs, batch_size):
            count = min(batch_size, runs - offset)
            rows.extend(runner.run_many(
                engine=engine,
                kyoku=context["kyoku"],
                honba=context["honba"],
                kyotaku=context["kyotaku"],
                bakaze=context["bakaze"],
                oya=oya,
                scores=context["scores"],
                dora_marker=dora,
                main_haipai=hand,
                first_discard=engine_discard,
                first_tsumo=first_tsumo,
                first_riichi=first_riichi,
                seed_start=(seed + offset, 0xDEAD),
                count=count,
            ))
            _emit(emit, "batch_completed", discard=discard, candidate=action_id, riichi=first_riichi, completed=min(offset + count, runs), total=runs)
        candidate = _summarize(rows, oya, discard, time.perf_counter() - candidate_started, first_riichi=first_riichi)
        candidates.append(candidate)
        _emit(emit, "candidate_completed", summary={
            key: value for key, value in _public(candidate).items() if key not in {"samples", "yaku"}
        })
    comparisons = [_compare(candidates[0], candidate) for candidate in candidates[1:]]
    return {
        "metrics_version": 2,
        "elapsed": time.perf_counter() - started,
        "device": str(device),
        "model": {key: model[key] for key in ("id", "label", "filename", "sha256", "version", "conv_channels", "num_blocks", "engine") if key in model},
        "runs": runs,
        "total_runs": runs,
        "seed": seed,
        "resolved_context": context,
        "resolved_input": {
            "main_haipai": hand,
            "first_tsumo": first_tsumo,
            "dora": dora,
        },
        "candidates": [_public(candidate) for candidate in candidates],
        "comparisons": comparisons,
        "merge_state_version": 1,
        "extension_history": [],
    }


def worker_main(request: dict[str, Any], event_queue) -> None:
    try:
        event_queue.put({"type": "completed", "result": run_analysis(request, event_queue.put)})
    except BaseException as exc:
        event_queue.put({"type": "failed", "error": str(exc), "traceback": traceback.format_exc()})

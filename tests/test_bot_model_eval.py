"""Unified inference unit tests; no model, native runtime, GPU or QQ required."""
from __future__ import annotations

import importlib
import json
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAW = {
    "dama": {"1p": 0.0, "2p": -1.0},
    "reach": {"1p": -2.0, "2p": 2.0},
    "reach_declare_q": 1.0,
}


@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "bot/src"))
    return SimpleNamespace(model=importlib.import_module("model_eval"),
                           parser=importlib.import_module("parser"))


def test_forward_builds_both_views_once_and_logs_full_labels(modules, monkeypatch, caplog):
    forward = Mock(return_value=RAW)
    monkeypatch.setattr(modules.model, "_forward_inference", forward)
    with caplog.at_level("INFO", logger="model_eval"):
        result = modules.model.model_forward("hand", "dora")
    forward.assert_called_once()
    assert [(t, r) for t, r, _ in result["top"]] == [("2p", True), ("1p", False)]
    assert "2pR(" in caplog.text and "1p(" in caplog.text
    assert "1pR(" not in caplog.text
    qp = result["qp"]
    reach_p = math.exp(1) / (1 + math.exp(-1) + math.exp(1))
    assert qp["riichi:2p"]["reach_p"] == pytest.approx(reach_p)
    assert qp["riichi:2p"]["p"] == pytest.approx(1 / (1 + math.exp(-4)))
    assert qp["1p"]["p"] + qp["2p"]["p"] + reach_p == pytest.approx(1)
    assert qp["riichi:1p"]["p"] + qp["riichi:2p"]["p"] == pytest.approx(1)



@pytest.mark.parametrize("alias_token,real", [
    ("", "distill_41b_infer"),
    ("m=agg", "distill_nova"),
    ("m=激进", "distill_nova"),
    ("模型=激进", "distill_nova"),
    # Internal IDs and unknown values are NOT a model switch: only the two
    # user-facing aliases above map to a different backend model.
    ("m=model_aggressive", "distill_41b_infer"),
    ("m=unknown", "distill_41b_infer"),
])
def test_model_entry_alias_coercion_matches_upstream(modules, monkeypatch, alias_token, real):
    """Entry semantics unchanged from upstream: only the user-facing aggressive
    aliases switch models; every other value falls back to the default model."""
    forward = Mock(return_value=RAW)
    monkeypatch.setattr(modules.model, "_forward_inference", forward)
    command = "/sim 66678m122344p340s d6m " + (alias_token + " " if alias_token else "")
    request, error = modules.parser.parse_sim_command(command)
    assert error is None
    assert forward.call_count == 1
    assert forward.call_args.kwargs["model_id"] == real


def test_reach_probe_is_one_conditional_state_not_a_duplicate_workflow(modules, monkeypatch):
    events = []

    class FakeMjaiBot:
        def __init__(self, engine, seat):
            assert seat == 3

        def react(self, encoded):
            event = json.loads(encoded)
            events.append(event)
            if event["type"] == "tsumo":
                return json.dumps({"meta": {"mask_bits": (1 << 9) | (1 << 10) | (1 << 37),
                                             "q_values": [0.0, -1.0, 1.0]}})
            if event["type"] == "reach":
                return json.dumps({"meta": {"mask_bits": (1 << 9) | (1 << 10),
                                             "q_values": [-2.0, 2.0]}})
            return None

    monkeypatch.setattr(modules.model, "get_cached_engine", Mock(return_value=object()))
    monkeypatch.setitem(sys.modules, "libriichi", SimpleNamespace(mjai=SimpleNamespace(Bot=FakeMjaiBot)))
    tiles = ["6m", "6m", "6m", "7m", "8m", "1p", "2p", "2p", "3p", "4p", "4p", "3s", "4s", "0s"]
    monkeypatch.setitem(sys.modules, "simulator.kyoku_sim_win", SimpleNamespace(parse_hand=lambda _: tiles))
    result = modules.model._forward_inference(
        "66678m122344p340s", "5m", honba=3, kyotaku=2, target_seat=3,
        scores={"self": 24000, "shimocha": 25000, "toimen": 25000},
    )
    assert result == RAW
    assert [e["type"] for e in events] == ["start_game", "start_kyoku", "tsumo", "reach"]
    assert events[1]["honba"] == 3 and events[1]["kyotaku"] == 2
    assert events[1]["scores"] == [25000, 25000, 24000, 24000]



def test_alias_import_and_inference_failure_need_no_native_runtime():
    script = '''
import importlib.abc, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split('.')[0] in {'torch', 'libriichi', 'mortal_app', 'simulator'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, NoNative())
sys.path.insert(0, 'bot/src')
import model_eval
assert model_eval.model_forward('hand', 'dora') == {'qp': {}, 'top': []}
'''
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr



def test_top_ties_follow_action_id_order(modules):
    raw = {"dama": {tile: 1.0 for tile in ["0p", "2z", "9m", "1p", "1m"]}}
    top = modules.model._build_top_candidates(raw)
    assert [tile for tile, _, _ in top] == ["1m", "9m", "1p", "2z"]


def test_model_root_is_env_overridable_not_hardcoded(monkeypatch, tmp_path):
    """Repo root may live outside the checkout; env override must win, and no
    contributor-specific absolute path may be baked into module import."""
    monkeypatch.setenv("MORTALSIM_ROOT", str(tmp_path))
    script = (
        "import sys; sys.path.insert(0, 'bot/src'); import model_eval; "
        "print(model_eval.MORTALSIM_ROOT)"
    )
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(tmp_path)

    # Only executable lines may be checked; explanatory comments legitimately
    # mention the old hardcoded path as the reason for the change.
    source = (ROOT / "bot/src/model_eval.py").read_text(encoding="utf-8")
    code_lines = [
        line.split("#", 1)[0]
        for line in source.splitlines()
    ]
    banned = ("D:/tenhoulib", "D:\\\\tenhoulib", "E:/AUbuntuProject", "E:\\\\AUbuntuProject")
    offenders = [line for line in code_lines if any(token in line for token in banned)]
    assert not offenders, offenders
    assert "MORTALSIM_ROOT" in source



def test_implicit_and_explicit_default_scores_deduct_the_same_kyotaku(modules):
    implicit = modules.model._build_scores(None, target_seat=3, kyotaku=2)
    explicit = modules.model._build_scores(
        {"self": 25000, "shimocha": 25000, "toimen": 25000}, target_seat=3, kyotaku=2,
    )
    assert implicit == explicit == [25000, 25000, 23000, 25000]



@pytest.mark.parametrize("wrapper", ["model_forward", "eval_model_qp", "get_top_model_discards"])
def test_all_forward_views_preserve_honba_kyotaku(modules, monkeypatch, wrapper):
    forward = Mock(return_value=RAW)
    monkeypatch.setattr(modules.model, "_forward_inference", forward)
    getattr(modules.model, wrapper)("hand", "dora", honba=5, kyotaku=3)
    assert forward.call_args.kwargs["honba"] == 5
    assert forward.call_args.kwargs["kyotaku"] == 3

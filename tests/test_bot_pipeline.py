"""Bot request/render integration tests with mocked inference and transport."""
from __future__ import annotations

import asyncio
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
COMMAND = "/sim 66678m122344p340s d6m x=4 seat=北 1000"
RAW = {
    "dama": {"1p": 0.0, "2p": -1.0},
    "reach": {"1p": -2.0, "2p": 2.0},
    "reach_declare_q": 1.0,
}



@pytest.fixture
def modules(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "bot" / "src"))
    model = importlib.import_module("model_eval")
    parser = importlib.import_module("parser")
    renderer = importlib.import_module("render_png")
    spec = importlib.util.spec_from_file_location("qq_bot_under_test", ROOT / "bot/src/bot.py")
    bot = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bot)
    return SimpleNamespace(model=model, parser=parser, renderer=renderer, bot=bot)



@pytest.mark.parametrize("mode", ["automatic", "explicit", "failed"])
def test_parser_through_execute_uses_one_inference_workflow(modules, monkeypatch, tmp_path, mode):
    forward = Mock(return_value=None if mode == "failed" else RAW)
    monkeypatch.setattr(modules.model, "_forward_inference", forward)
    base_command = COMMAND.replace("1000", "S2-3-2 P250,250,230,250 1000")
    command = base_command.replace(" x=4", " c=2pr,1p x=4") if mode == "explicit" else base_command
    request, error = modules.parser.parse_sim_command(command)
    assert error is None
    assert forward.call_count == (0 if mode == "explicit" else 1)
    assert ("_model_qp" in request) == (mode != "explicit")
    if mode == "failed":
        assert request["_model_qp"] == {}
        assert len(request["discards"]) == 2  # existing fallback candidates

    candidate = {"candidate": "riichi:2p", "discard": "riichi:2p", "first_riichi": True,
                 "value": {"point": {"value": 9708}}}
    worker = object.__new__(modules.bot.Bot)
    worker.mortal_cfg = {"model_id": "model_balanced"}
    worker.render_cfg = {"output_dir": str(tmp_path), "tile_assets_dir": "unused", "font_path": "unused"}
    worker.mortal = SimpleNamespace(
        create_run=AsyncMock(return_value="test-run"),
        wait_completed=AsyncMock(return_value={"result": {"candidates": [candidate]}, "request": {}}),
    )
    worker.send_group_result = AsyncMock()
    render = Mock()
    monkeypatch.setattr(modules.bot, "render_png", render)
    asyncio.run(worker.execute({"request": request, "runs": 1000, "group_id": 1, "user_id": 2}))

    assert forward.call_count == 1
    sent = worker.mortal.create_run.call_args.args[0]
    assert "_model_qp" not in sent
    assert sent["model_id"] == "distill_41b_infer"
    assert forward.call_args.kwargs["target_seat"] == 3
    assert forward.call_args.kwargs["model_id"] == "distill_41b_infer"
    assert forward.call_args.kwargs["round_str"] == "S2"
    assert forward.call_args.kwargs["honba"] == sent["honba"] == 3
    assert forward.call_args.kwargs["kyotaku"] == sent["kyotaku"] == 2
    assert render.call_args.kwargs["recommended_tile"] == "2pR"
    if mode != "explicit":
        assert render.call_args.kwargs["model_qp"] is request["_model_qp"]
    else:
        assert render.call_args.kwargs["model_qp"] == modules.model._build_qp_map(RAW)
    assert "2pR" in worker.send_group_result.call_args.args[2]
    assert "riichi:" not in worker.send_group_result.call_args.args[2]



@pytest.mark.parametrize("candidate", [
    {"candidate": "riichi:2p"},
    {"candidate": "立直:2p"},
    {"candidate": "2p", "discard": "2p", "first_riichi": True},
    {"discard": "2p", "riichi": True},
])
def test_riichi_label_and_qp_never_resolve_to_dama(modules, candidate):
    renderer = modules.renderer
    qp = {"2p": {"q": -4.0, "p": 0.01}, "riichi:2p": {"q": 1.5, "p": 0.86}}
    assert renderer._label_zh(candidate) == "2pR"
    assert renderer._lookup_model_qp(qp, candidate) is qp["riichi:2p"]
    assert renderer._lookup_model_qp({"2p": qp["2p"]}, candidate) is None



@pytest.mark.parametrize("recommendation", ["2pR", "2pr", "riichi:2p", "立直:2p", "立直 2p"])
def test_recommendation_identity_keeps_action_separate(modules, recommendation):
    base, keys = modules.renderer._rec_identities(recommendation)
    assert base == "2p"
    assert "2pR" in keys
    assert "2p" not in keys and "2pk" not in keys
    _, dama_keys = modules.renderer._rec_identities("2p")
    assert "2pR" not in dama_keys
    _, kan_keys = modules.renderer._rec_identities("2pk")
    assert "2p杠" in kan_keys and "2p" not in kan_keys



@pytest.mark.parametrize("candidate", [
    {"candidate": "tsumo", "discard": "2p"},
    {"candidate": "ron", "discard": "2p"},
    {"candidate": "pass", "discard": "2p"},
    {"candidate": "chi:45m>2p", "discard": "2p"},
    {"candidate": "pon:5z>2p", "discard": "2p"},
    {"candidate": "2p", "discard": "2p", "first_kan": True},
])
def test_non_discard_actions_do_not_borrow_discard_qp(modules, candidate):
    assert modules.renderer._lookup_model_qp({"2p": {"q": 1.0, "p": 1.0}}, candidate) is None



def test_plain_and_red_discards_keep_their_own_qp(modules):
    qp = {"2p": {"q": 0.0, "p": 0.2}, "0p": {"q": 1.0, "p": 0.8}}
    assert modules.renderer._lookup_model_qp(qp, {"candidate": "2p", "riichi": {"rate": 0.9}}) is qp["2p"]
    assert modules.renderer._lookup_model_qp(qp, {"candidate": "5pr"}) is qp["0p"]
    assert modules.model.MORTALSIM_ROOT == ROOT



@pytest.mark.parametrize("recommended,starred", [("2pR", "2pR ★"), ("2p", "2p ★")])
def test_renderer_highlights_only_the_recommended_action(modules, monkeypatch, tmp_path, recommended, starred):
    from PIL import Image, ImageDraw, ImageFont

    # Portable fixture font: actual local CJK font is separately checked in the saved preview.
    font = ImageFont.load_default()
    monkeypatch.setattr(modules.renderer.ImageFont, "truetype", lambda *args, **kwargs: font)
    texts = []
    positions = []
    draw_text = ImageDraw.ImageDraw.text

    def capture(draw, xy, text, *args, **kwargs):
        texts.append(str(text))
        positions.append((str(text), xy[0]))
        return draw_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture)
    result = {
        "config": {"hand": "2p2p", "target_seat": 0, "runs": 1},
        "candidates": [
            {"candidate": "2p", "discard": "2p", "first_riichi": True},
            {"candidate": "2p", "discard": "2p"},
        ],
    }
    output = tmp_path / "preview.png"
    modules.renderer.render_png(result, tmp_path, "fixture-font", output, recommended_tile=recommended,
                                model_qp={"2p": {"q": -1.0, "p": 0.1},
                                          "riichi:2p": {"q": 2.0, "p": 0.9, "riichi": 1.0}})
    with Image.open(output) as image:
        assert image.size == (1120, 750)
        image.verify()
    assert [text for text in texts if text.endswith(" ★")] == [starred, starred]
    assert "模型Q" not in texts
    assert "-1.000" not in texts and "2.000" not in texts
    assert "归一P" in texts
    assert "10.0%" in texts and "90.0%" in texts
    # 归一P 仍位于表格末端；精确列间距/迷你条几何另由布局测试验证。
    p_positions = [x for text, x in positions if text in ("10.0%", "90.0%", "归一P")]
    assert p_positions and all(x > 1000 for x in p_positions)



@pytest.mark.parametrize("candidate,legacy_label", [
    ({"candidate": "tsumo"}, "自摸"),
    ({"candidate": "kyushu:kk"}, "kk"),
    ({"candidate": "pass"}, "见逃"),
    ({"candidate": "ron"}, "荣和"),
])
def test_special_recommendations_use_shared_labels(modules, candidate, legacy_label):
    label = modules.bot.candidate_label(candidate)
    assert label == modules.renderer._label_zh(candidate)
    assert label in modules.renderer._rec_identities(label)[1]
    assert label in modules.renderer._rec_identities(legacy_label)[1]

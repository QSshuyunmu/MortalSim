"""Geometry regressions for the full-width outcome table (no inference required)."""
from __future__ import annotations

import copy
import importlib
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "bot/src"))
    module = importlib.import_module("render_png")
    # Use Pillow's portable TrueType default with the requested point sizes.
    fonts = {size: ImageFont.load_default(size=size) for size in range(8, 21)}
    monkeypatch.setattr(module.ImageFont, "truetype", lambda path, size, **kwargs: fonts[size])
    return module


def capture_table(renderer, monkeypatch, tmp_path, candidates, qp):
    texts, bars = [], []
    text = ImageDraw.ImageDraw.text
    rectangle = ImageDraw.ImageDraw.rounded_rectangle

    def capture_text(draw, xy, value, *args, **kwargs):
        if draw._image.size == (1120, 750) and 120 <= xy[1] < 144 + 32 * len(candidates):
            font = kwargs["font"]
            bbox = draw.textbbox(xy, value, font=font)
            texts.append((str(value), bbox, draw.textlength(value, font=font)))
        return text(draw, xy, value, *args, **kwargs)

    def capture_bar(draw, xy, *args, **kwargs):
        if kwargs.get("fill") == (20, 30, 30, 255) and xy[3] - xy[1] == 7:
            bars.append(xy)
        return rectangle(draw, xy, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(ImageDraw.ImageDraw, "text", capture_text)
        m.setattr(ImageDraw.ImageDraw, "rounded_rectangle", capture_bar)
        output = tmp_path / "layout.png"
        renderer.render_png({"config": {"hand": "2p2p", "runs": 2000}, "candidates": candidates},
                            tmp_path, "fixture-font", output, model_qp=qp)
        with Image.open(output) as image:
            image.verify()
    return texts, bars


def test_pon_report_names_the_actual_discarding_seat(renderer, monkeypatch, tmp_path):
    from parser import parse_sim_command

    command = ("/sim 112m13558p2236s4z d5p seat=北 x=4 E3-0 "
               "river=东:9s,1z,8pt,5p/南:3z,9p,5z/西:1p,3z,2p/北:9m,2z,7z "
               "P277,208,264,251 c=pon:5p,pass 50")
    request, error = parse_sim_command(command)
    assert error is None, error
    candidate = row()
    candidate.update(candidate="pon:5p", discard="pon:5p")
    captured = []
    original_text = ImageDraw.ImageDraw.text

    def capture_text(draw, xy, text, *args, **kwargs):
        captured.append(str(text))
        return original_text(draw, xy, text, *args, **kwargs)

    monkeypatch.setattr(ImageDraw.ImageDraw, "text", capture_text)
    renderer.render_png({"config": request, "candidates": [candidate]},
                        tmp_path, "fixture-font", tmp_path / "pon.png")
    assert "东家打出 5p · 待响应（未摸牌）" in captured
    assert not any("上家打出" in value for value in captured)


def row():
    return {"candidate": "2z", "discard": "2z",
            "value": {"point": {"value": -237, "ci95": [-421, -52]}},
            "agari_rate": .29, "win": {"average_point": 4337},
            "outcome": {"self_tsumo": {"rate": .09}},
            "houjuu_rate": .13, "riichi_rate": .057, "fuuro_rate": .732}


@pytest.mark.parametrize("with_p", [True, False])
def test_column_and_bar_anchors_do_not_grow_with_row_count(renderer, monkeypatch, tmp_path, with_p):
    qp = {"2z": {"q": .442, "p": .773}} if with_p else None
    layouts = []
    for count in [2, 4]:
        texts, bars = capture_table(renderer, monkeypatch, tmp_path, [row() for _ in range(count)], qp)
        headers = [(value, bbox[0]) for value, bbox, _ in texts if bbox[1] < 144]
        layouts.append((headers, bars[0][0]))
        assert len(bars) == count
        assert all(bar[0] == pytest.approx(bars[0][0]) for bar in bars)
        ci = [(bbox, advance) for value, bbox, advance in texts if value.startswith("CI ")]
        text_right = max(bbox[0] + advance for bbox, advance in ci)
        assert bars[0][0] - text_right == pytest.approx(4.0, abs=1)
        agari_x = next(bbox[0] for value, bbox, _ in texts if value == "和牌率")
        assert agari_x > bars[0][2] + 4
        for _, bbox, _ in texts:
            assert 432 <= bbox[0] < bbox[2] <= 1083
    assert layouts[0] == layouts[1]


def test_long_ci_and_two_stage_probability_fit_without_overlap(renderer, monkeypatch, tmp_path):
    candidate = row()
    candidate.update(candidate="riichi:2p", discard="riichi:2p", first_riichi=True,
                     agari_rate=1.0, houjuu_rate=1.0, riichi_rate=1.0, fuuro_rate=1.0)
    candidate["win"]["average_point"] = 99999
    candidate["outcome"]["self_tsumo"]["rate"] = 1.0
    candidate["value"]["point"] = {"value": 100000, "ci95": [-100000, 100000]}
    qp = {"riichi:2p": {"q": 123.456, "p": 1.0, "riichi": 1.0, "reach_p": 1.0}}
    candidates = [copy.deepcopy(candidate) for _ in range(4)]
    candidates[0].update(candidate="chi:4m5m>2p", discard="2p", first_riichi=False)
    texts, bars = capture_table(renderer, monkeypatch, tmp_path, candidates, qp)
    assert any("→" in value for value, _, _ in texts)
    assert "模型Q" not in [value for value, _, _ in texts]
    for i, (value, bbox, _) in enumerate(texts):
        assert bbox[2] <= 1083, value
        for other, box, _ in texts[i + 1:]:
            overlap = min(bbox[2], box[2]) > max(bbox[0], box[0]) and min(bbox[3], box[3]) > max(bbox[1], box[1])
            assert not overlap, (value, other)
        for bar in bars:
            overlap = min(bbox[2], bar[2]) > max(bbox[0], bar[0]) and min(bbox[3], bar[3]) > max(bbox[1], bar[1])
            assert not overlap, (value, bar)

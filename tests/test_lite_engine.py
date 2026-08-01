from __future__ import annotations

import zipfile

import numpy as np
import pytest

from mortal.lite_engine import MortalLiteEngine
from mortal.lite_weights import LiteWeightError, load_mortal_state


def test_lite_action_contract_is_stable() -> None:
    assert MortalLiteEngine.engine_type == "mortal-lite"
    assert MortalLiteEngine.decision_contract == "stable_advantage_v2"


def test_lite_selector_uses_legal_lowest_id_tie_break() -> None:
    scores = np.full((2, 46), -10.0, dtype=np.float32)
    masks = np.zeros((2, 46), dtype=bool)
    masks[:, [3, 9]] = True
    scores[0, 3] = scores[0, 9] = 4.0
    scores[1, 3], scores[1, 9] = -3.0, -2.0
    assert MortalLiteEngine._select_actions(scores, masks) == [3, 9]


def test_lite_selector_rejects_nan_and_empty_mask() -> None:
    scores = np.zeros((1, 46), dtype=np.float32)
    masks = np.zeros((1, 46), dtype=bool)
    masks[0, 2] = True
    scores[0, 2] = np.nan
    try:
        MortalLiteEngine._select_actions(scores, masks)
    except ValueError as exc:
        assert "NaN" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("NaN score was accepted")
    try:
        MortalLiteEngine._select_actions(np.zeros((1, 46), np.float32), np.zeros((1, 46), bool))
    except ValueError as exc:
        assert "no legal action" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("empty mask was accepted")


def test_lite_input_validation_rejects_wrong_shapes() -> None:
    engine = object.__new__(MortalLiteEngine)
    engine.capacity = 4
    engine._handle = None
    try:
        engine.react_batch(np.zeros((1, 1012, 34), dtype=np.float32), np.zeros((1, 45), dtype=bool))
    except ValueError as exc:
        assert "mask shape" in str(exc)
    else:  # pragma: no cover - assertion is the test
        raise AssertionError("invalid mask shape was accepted")


def test_lite_weight_reader_rejects_compressed_zip_entries(tmp_path) -> None:
    checkpoint = tmp_path / "compressed.pth"
    with zipfile.ZipFile(checkpoint, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("archive/data.pkl", b"not evaluated")
    with pytest.raises(LiteWeightError, match="compressed checkpoint"):
        load_mortal_state(checkpoint)

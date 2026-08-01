from __future__ import annotations

import numpy as np

from mortal.lite_engine import MortalLiteEngine


def test_lite_action_contract_is_stable() -> None:
    assert MortalLiteEngine.engine_type == "mortal-lite"


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

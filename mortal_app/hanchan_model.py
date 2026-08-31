"""Hanchan final-rank probability model (LightGBM).

Maps a next-kyoku state (scores, bakaze, kyoku_num, honba, kyotaku, oya) to
per-seat final-rank probabilities.  The model is trained on real Tenhou
Houou game logs and is statistical, not a Mahjong AI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import scipy.sparse
if not hasattr(scipy.sparse, "spmatrix"):
    try:
        from scipy.sparse._base import _spbase
        scipy.sparse.spmatrix = _spbase
    except Exception:
        pass
import numpy as np

HOUOU_PT_TABLES = {
    "houou_7": [90, 45, 0, -135],
    "houou_8": [90, 45, 0, -150],
    "houou_9": [90, 45, 0, -165],
    "houou_10": [90, 45, 0, -180],
}

FEATURE_NAMES = [
    "s0_norm", "s1_norm", "s2_norm", "s3_norm",
    "kyoku_idx_norm", "honba", "kyotaku_norm",
    "oya_0", "oya_1", "oya_2", "oya_3",
]


def encode_state(scores, bakaze: str, kyoku_num: int, honba: int, kyotaku: int, oya: int) -> np.ndarray:
    """Encode a next-kyoku state exactly like training-time features."""
    total = float(sum(scores) + 1000 * kyotaku)
    if bakaze == "E":
        kyoku_idx = kyoku_num - 1
    elif bakaze == "S":
        kyoku_idx = kyoku_num + 3
    else:
        kyoku_idx = kyoku_num + 7
    return np.array([
        scores[0] / total,
        scores[1] / total,
        scores[2] / total,
        scores[3] / total,
        kyoku_idx / 12.0,
        float(honba),
        (1000.0 * kyotaku) / total,
        1.0 if oya == 0 else 0.0,
        1.0 if oya == 1 else 0.0,
        1.0 if oya == 2 else 0.0,
        1.0 if oya == 3 else 0.0,
    ], dtype=np.float32)


class HanchanRankModel:
    def __init__(self, model_dir: str | Path):
        self.model_dir = Path(model_dir)
        import lightgbm as lgb

        self._boosters = []
        for seat in range(4):
            path = self.model_dir / f"hanchan_rank_lgb_seat{seat}.txt"
            self._boosters.append(lgb.Booster(model_file=str(path)))
        self.manifest = json.loads(
            (self.model_dir / "hanchan_rank_model_manifest.json").read_text(encoding="utf-8")
        )

    @property
    def model_id(self) -> str:
        return str(self.manifest.get("model_id", "hanchan-rank-lgb-v1"))

    @property
    def model_sha256(self) -> str:
        digest = hashlib.sha256()
        for path in sorted(self.model_dir.glob("hanchan_rank_lgb_seat*.txt")):
            digest.update(path.read_bytes())
        digest.update((self.model_dir / "hanchan_rank_model_manifest.json").read_bytes())
        return digest.hexdigest()

    def predict_proba(self, scores, bakaze: str, kyoku_num: int, honba: int, kyotaku: int, oya: int) -> np.ndarray:
        """Return shape (4, 4): probs[seat][rank_index]."""
        x = encode_state(scores, bakaze, kyoku_num, honba, kyotaku, oya).reshape(1, -1)
        probs = np.zeros((4, 4), dtype=np.float64)
        for seat, booster in enumerate(self._boosters):
            p = booster.predict(x)
            probs[seat] = np.asarray(p[0], dtype=np.float64)
        # Normalize defensively; LightGBM probabilities should already sum to 1.
        probs = probs / probs.sum(axis=1, keepdims=True)
        return probs

    def predict_seat(self, scores, bakaze: str, kyoku_num: int, honba: int, kyotaku: int, oya: int, seat: int) -> np.ndarray:
        return self.predict_proba(scores, bakaze, kyoku_num, honba, kyotaku, oya)[seat]

    def expected_rank(self, scores, bakaze: str, kyoku_num: int, honba: int, kyotaku: int, oya: int, seat: int) -> float:
        p = self.predict_seat(scores, bakaze, kyoku_num, honba, kyotaku, oya, seat)
        return float(np.dot(p, np.arange(1, 5, dtype=np.float64)))

    def pt_ev(self, scores, bakaze: str, kyoku_num: int, honba: int, kyotaku: int, oya: int, seat: int) -> dict[str, float]:
        p = self.predict_seat(scores, bakaze, kyoku_num, honba, kyotaku, oya, seat)
        return {
            name: float(np.dot(p, np.array(table, dtype=np.float64)))
            for name, table in HOUOU_PT_TABLES.items()
        }

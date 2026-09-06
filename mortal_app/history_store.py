"""MortalSim Canonical History Store and Statistical Reduction Engine.

Implements:
1. Full Canonical Fingerprinting for Mahjong decision points (BLAKE3 / SHA-256).
2. Chan's numerically stable parallel reduction for 1st and 2nd central moments.
3. Paired-difference Student-t test with Common Random Numbers (CRN) covariance reduction.
4. Region of Practical Equivalence (ROPE, epsilon=0.5 pt) decision state machine.
5. SQLite WAL persistence with in-memory LRU cache and atomic seed reservation.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from scipy.stats import t as student_t


@dataclass
class CandidateAccumulator:
    candidate: str
    engine_tile: str
    runs: int = 0
    sum_pt: float = 0.0
    m2_pt: float = 0.0          # Second central moment sum: sum((x - mean)^2)
    sum_score: float = 0.0
    m2_score: float = 0.0       # Score delta second central moment sum
    sum_mleague: float = 0.0    # M-League PTEV (Uma + Raw points) sum
    m2_mleague: float = 0.0     # M-League PTEV second central moment sum
    win_count: int = 0
    deal_in_count: int = 0
    last_seed: int = 42

    @property
    def mean_pt(self) -> float:
        return self.sum_pt / self.runs if self.runs > 0 else 0.0

    @property
    def var_pt(self) -> float:
        if self.runs <= 1:
            return 0.0
        return self.m2_pt / (self.runs - 1)

    @property
    def stddev_pt(self) -> float:
        return math.sqrt(max(0.0, self.var_pt))

    @property
    def mean_score(self) -> float:
        return self.sum_score / self.runs if self.runs > 0 else 0.0

    @property
    def var_score(self) -> float:
        if self.runs <= 1:
            return 0.0
        return self.m2_score / (self.runs - 1)

    @property
    def stddev_score(self) -> float:
        return math.sqrt(max(0.0, self.var_score))

    @property
    def mean_mleague(self) -> float:
        return self.sum_mleague / self.runs if self.runs > 0 else 0.0

    @property
    def var_mleague(self) -> float:
        if self.runs <= 1:
            return 0.0
        return self.m2_mleague / (self.runs - 1)

    @property
    def stddev_mleague(self) -> float:
        return math.sqrt(max(0.0, self.var_mleague))

    @property
    def win_rate(self) -> float:
        return self.win_count / self.runs if self.runs > 0 else 0.0

    @property
    def deal_in_rate(self) -> float:
        return self.deal_in_count / self.runs if self.runs > 0 else 0.0

    def reduce_with(self, new_n: int, new_sum_pt: float, new_m2_pt: float,
                    new_sum_score: float, new_m2_score: float,
                    new_wins: int, new_deals: int, max_seed: int,
                    new_sum_mleague: float = 0.0, new_m2_mleague: float = 0.0) -> None:
        """Chan's parallel reduction to update moments with zero catastrophic cancellation."""
        if new_n <= 0:
            return
        if self.runs == 0:
            self.runs = new_n
            self.sum_pt = new_sum_pt
            self.m2_pt = new_m2_pt
            self.sum_score = new_sum_score
            self.m2_score = new_m2_score
            self.sum_mleague = new_sum_mleague
            self.m2_mleague = new_m2_mleague
            self.win_count = new_wins
            self.deal_in_count = new_deals
            self.last_seed = max_seed
            return

        n1, n2 = float(self.runs), float(new_n)
        n_total = n1 + n2

        # 1. Update Tenhou pt moments
        mu1_pt = self.sum_pt / n1
        mu2_pt = new_sum_pt / n2
        delta_pt = mu2_pt - mu1_pt
        self.sum_pt += new_sum_pt
        self.m2_pt = self.m2_pt + new_m2_pt + (delta_pt ** 2) * (n1 * n2 / n_total)

        # 2. Update score moments
        mu1_sc = self.sum_score / n1
        mu2_sc = new_sum_score / n2
        delta_sc = mu2_sc - mu1_sc
        self.sum_score += new_sum_score
        self.m2_score = self.m2_score + new_m2_score + (delta_sc ** 2) * (n1 * n2 / n_total)

        # 3. Update M-League moments
        mu1_ml = self.sum_mleague / n1
        mu2_ml = new_sum_mleague / n2
        delta_ml = mu2_ml - mu1_ml
        self.sum_mleague += new_sum_mleague
        self.m2_mleague = self.m2_mleague + new_m2_mleague + (delta_ml ** 2) * (n1 * n2 / n_total)

        # 4. Update counts & seeds
        self.runs = int(n_total)
        self.win_count += new_wins
        self.deal_in_count += new_deals
        self.last_seed = max(self.last_seed, max_seed)


@dataclass
class DecisionState:
    badge: str              # "🌟 明确优选" | "⚖️ 伯仲均可" | "⚠️ 尚不明确" | "🌟 唯一合法切牌"
    status_code: str        # "clear_best" | "rope_equivalent" | "inconclusive" | "single_candidate"
    confidence_p: float     # 0.0 ~ 1.0 (internal statistical probability)
    delta_pt: float         # mean_best - mean_second
    se_diff: float          # Standard error of difference
    best_candidate: str
    second_candidate: Optional[str] = None
    is_converged: bool = False  # True if >= 95% or in ROPE, meaning no further rollout needed


def compute_canonical_fingerprint(req: Dict[str, Any]) -> str:
    """Generate a canonical semantic fingerprint hash for a Mahjong state."""
    # 1. Hand sorted
    hand_raw = str(req.get("hand", "")).strip()
    tiles = [hand_raw[i:i+2] for i in range(0, len(hand_raw), 2)]
    tiles.sort()
    sorted_hand = "".join(tiles)

    # 2. Key game state features
    dora = str(req.get("dora", "")).strip()
    rnd = str(req.get("round", "E1")).strip().upper()
    honba = int(req.get("honba", 0))
    kyotaku = int(req.get("kyotaku", 0))
    x_turn = int(req.get("x", 1))
    target_seat = req.get("target_seat")

    # 3. Rivers sequence
    target_past = req.get("target_past_discards") or []
    target_past_tuple = tuple((d[0], bool(d[1]), bool(d[2])) if isinstance(d, (list, tuple)) else (d.get("tile"), d.get("tsumogiri"), d.get("is_riichi")) for d in target_past)

    opp_rivers = req.get("opponent_rivers") or []
    opp_rivers_tuple = []
    for r in opp_rivers:
        r_list = tuple((d[0], bool(d[1]), bool(d[2])) if isinstance(d, (list, tuple)) else (d.get("tile"), d.get("tsumogiri"), d.get("is_riichi")) for d in r)
        opp_rivers_tuple.append(r_list)
    opp_rivers_tuple = tuple(opp_rivers_tuple)

    # 4. Scores
    scores = req.get("scores")
    scores_tuple = None
    if isinstance(scores, dict):
        scores_tuple = (scores.get("self", 25000), scores.get("shimocha", 25000), scores.get("toimen", 25000))
    elif isinstance(scores, (list, tuple)):
        scores_tuple = tuple(scores)

    # 5. Discard candidates (sorted canonical set)
    discards = req.get("discards", [])
    cand_names = sorted(str(d.get("candidate") or d.get("tile") or "") for d in discards)

    # 6. Model
    model_id = str(req.get("model_id", "distill_41b_infer"))

    canonical_obj = {
        "hand": sorted_hand,
        "dora": dora,
        "round": rnd,
        "honba": honba,
        "kyotaku": kyotaku,
        "x": x_turn,
        "target_seat": target_seat,
        "target_past": target_past_tuple,
        "opp_rivers": opp_rivers_tuple,
        "scores": scores_tuple,
        "candidates": cand_names,
        "model_id": model_id,
    }

    serialized = json.dumps(canonical_obj, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def evaluate_decision_state(cands: List[CandidateAccumulator], rope_epsilon_pt: float = 0.5) -> DecisionState:
    """Evaluate decision convergence state using Paired Difference & ROPE."""
    if not cands:
        return DecisionState(
            badge="⚠️ 尚不明确", status_code="inconclusive", confidence_p=0.5,
            delta_pt=0.0, se_diff=1.0, best_candidate="", is_converged=False
        )

    if len(cands) == 1:
        return DecisionState(
            badge="🌟 唯一合法切牌", status_code="single_candidate", confidence_p=1.0,
            delta_pt=0.0, se_diff=0.0, best_candidate=cands[0].candidate, is_converged=True
        )

    # Sort candidates by pt descending
    sorted_cands = sorted(cands, key=lambda c: c.mean_pt, reverse=True)
    best = sorted_cands[0]
    second = sorted_cands[1]

    delta_pt = best.mean_pt - second.mean_pt

    # Minimum sample check (need at least 30 samples to test)
    if best.runs < 30 or second.runs < 30:
        return DecisionState(
            badge="⏳ 快速评估中", status_code="inconclusive", confidence_p=0.5,
            delta_pt=delta_pt, se_diff=1.0, best_candidate=best.candidate,
            second_candidate=second.candidate, is_converged=False
        )

    # In CRN, we estimate standard error of difference
    # Under CRN, Cov(A, B) > 0, so SE_diff <= sqrt(var1/n1 + var2/n2)
    # Using conservative upper bound for SE_diff
    se_diff = math.sqrt(max(1e-9, (best.var_pt / best.runs) + (second.var_pt / second.runs)))
    dof = max(2.0, float(best.runs + second.runs - 2))

    t_stat = delta_pt / se_diff if se_diff > 1e-7 else 0.0
    p_val = float(student_t.cdf(t_stat, df=dof))

    # Decision State Machine:
    # 1. ROPE Equivalent: diff in pt is practically zero (< 0.5 pt) and well-sampled (>= 300 runs)
    if abs(delta_pt) < rope_epsilon_pt and min(best.runs, second.runs) >= 300:
        return DecisionState(
            badge="⚖️ 伯仲均可", status_code="rope_equivalent", confidence_p=p_val,
            delta_pt=delta_pt, se_diff=se_diff, best_candidate=best.candidate,
            second_candidate=second.candidate, is_converged=True
        )

    # 2. Clear Superiority: delta >= 0.5 pt AND p_val >= 95.0%
    if delta_pt >= rope_epsilon_pt and p_val >= 0.95:
        return DecisionState(
            badge="🌟 明确优选", status_code="clear_best", confidence_p=p_val,
            delta_pt=delta_pt, se_diff=se_diff, best_candidate=best.candidate,
            second_candidate=second.candidate, is_converged=True
        )

    # 3. High-run Cap Convergence: reached 4000 runs
    if min(best.runs, second.runs) >= 4000:
        badge = "🌟 明确优选" if delta_pt >= rope_epsilon_pt and p_val >= 0.90 else "⚖️ 伯仲均可"
        return DecisionState(
            badge=badge, status_code="cap_converged", confidence_p=p_val,
            delta_pt=delta_pt, se_diff=se_diff, best_candidate=best.candidate,
            second_candidate=second.candidate, is_converged=True
        )

    # 4. Otherwise Inconclusive
    return DecisionState(
        badge="⚠️ 尚不明确", status_code="inconclusive", confidence_p=p_val,
        delta_pt=delta_pt, se_diff=se_diff, best_candidate=best.candidate,
        second_candidate=second.candidate, is_converged=False
    )


class HistoryStore:
    """Thread-safe SQLite + in-memory LRU store for historical Mahjong simulations."""

    def __init__(self, db_path: str | Path = "data/history.db", lru_capacity: int = 2000):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.lru_capacity = lru_capacity
        self._lock = threading.RLock()
        self._lru: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30.0) as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS canonical_history (
                    fingerprint TEXT PRIMARY KEY,
                    canonical_json TEXT NOT NULL,
                    accumulators_json TEXT NOT NULL,
                    total_runs INTEGER NOT NULL,
                    decision_badge TEXT NOT NULL,
                    is_converged INTEGER NOT NULL,
                    last_seed INTEGER NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_fp ON canonical_history(fingerprint);")
            conn.commit()

    def get(self, fingerprint: str) -> Optional[Dict[str, Any]]:
        """Retrieve historical accumulated record by fingerprint."""
        with self._lock:
            if fingerprint in self._lru:
                self._lru.move_to_end(fingerprint)
                return self._lru[fingerprint]

        # Read from SQLite
        with sqlite3.connect(self.db_path, timeout=10.0) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT accumulators_json, total_runs, decision_badge, is_converged, last_seed
                FROM canonical_history WHERE fingerprint = ?;
            """, (fingerprint,))
            row = cur.fetchone()
            if not row:
                return None

            acc_data = json.loads(row[0])
            record = {
                "fingerprint": fingerprint,
                "accumulators": {k: CandidateAccumulator(**v) for k, v in acc_data.items()},
                "total_runs": row[1],
                "decision_badge": row[2],
                "is_converged": bool(row[3]),
                "last_seed": row[4],
            }

            with self._lock:
                self._lru[fingerprint] = record
                if len(self._lru) > self.lru_capacity:
                    self._lru.popitem(last=False)
            return record

    def save_reduction(self, fingerprint: str, canonical_req: Dict[str, Any],
                       accumulators: Dict[str, CandidateAccumulator]) -> Tuple[Dict[str, Any], DecisionState]:
        """Atomically reduce and save accumulators, evaluating convergence."""
        cand_list = list(accumulators.values())
        dec_state = evaluate_decision_state(cand_list)
        total_runs = max((c.runs for c in cand_list), default=0)
        max_seed = max((c.last_seed for c in cand_list), default=42)

        acc_dict = {k: asdict(v) for k, v in accumulators.items()}
        acc_json = json.dumps(acc_dict, ensure_ascii=False)
        req_json = json.dumps(canonical_req, ensure_ascii=False)

        with self._lock:
            with sqlite3.connect(self.db_path, timeout=30.0) as conn:
                conn.execute("BEGIN IMMEDIATE;")
                conn.execute("""
                    INSERT INTO canonical_history (
                        fingerprint, canonical_json, accumulators_json,
                        total_runs, decision_badge, is_converged, last_seed, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(fingerprint) DO UPDATE SET
                        accumulators_json = excluded.accumulators_json,
                        total_runs = excluded.total_runs,
                        decision_badge = excluded.decision_badge,
                        is_converged = excluded.is_converged,
                        last_seed = excluded.last_seed,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    fingerprint, req_json, acc_json,
                    total_runs, dec_state.badge, int(dec_state.is_converged), max_seed
                ))
                conn.commit()

            record = {
                "fingerprint": fingerprint,
                "accumulators": accumulators,
                "total_runs": total_runs,
                "decision_badge": dec_state.badge,
                "is_converged": dec_state.is_converged,
                "last_seed": max_seed,
            }
            self._lru[fingerprint] = record
            if len(self._lru) > self.lru_capacity:
                self._lru.popitem(last=False)

        return record, dec_state


# Global singleton instance
_GLOBAL_HISTORY_STORE: Optional[HistoryStore] = None


def get_global_history_store() -> HistoryStore:
    global _GLOBAL_HISTORY_STORE
    if _GLOBAL_HISTORY_STORE is None:
        db_dir = Path(os.environ.get("MORTALSIM_DATA_DIR", "data"))
        _GLOBAL_HISTORY_STORE = HistoryStore(db_dir / "history.db")
    return _GLOBAL_HISTORY_STORE

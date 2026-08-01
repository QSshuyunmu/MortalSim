"""Application service boundaries around the existing simulation worker."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable
from uuid import UUID

from mortal_app.service import run_analysis


class SimulationService:
    """Keep request execution behind a stable API-facing boundary."""

    @staticmethod
    def run(request: dict[str, Any], emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        return run_analysis(request, emit)


class StatisticsService:
    """Build the versioned result envelope without exposing worker internals."""

    @staticmethod
    def envelope(
        *,
        run_id: UUID,
        created_at: datetime,
        config: dict[str, Any],
        raw_result: dict[str, Any],
        gpu_telemetry: dict[str, Any] | None,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        expected = config.get("expected_trace_hash")
        actual = None
        candidates = raw_result.get("candidates", [])
        if candidates and expected:
            samples = candidates[0].get("samples", {})
            for items in samples.values():
                if items:
                    actual = items[0].get("trace_hash")
                    break
            if actual != expected:
                warnings.append("replay_mismatch: 复跑 trace hash 与原样本不一致")
        return {
            **raw_result,
            "schema_version": 3,
            "metrics_version": 2,
            "decision_contract": raw_result.get("decision_contract")
            or config.get("decision_contract", "stable_advantage_v2"),
            "runtime": raw_result.get("runtime") or {},
            "run_id": str(run_id),
            "created_at": created_at.isoformat(),
            "config": config,
            "engine": {
                "name": config.get("engine", "lite"),
                "amp": config.get("engine", "lite") == "python",
                "decision_contract": raw_result.get("decision_contract")
                or config.get("decision_contract", "stable_advantage_v2"),
            },
            "model": raw_result.get("model") or {"id": config.get("model_id", "mortal-v4-20240308")},
            "hardware": {"device": raw_result.get("device")},
            "candidates": candidates,
            "gpu_telemetry": gpu_telemetry,
            "replay": {"expected_trace_hash": expected, "actual_trace_hash": actual, "mismatch": bool(expected and expected != actual)} if config.get("replay_of") else None,
            "warnings": warnings,
        }

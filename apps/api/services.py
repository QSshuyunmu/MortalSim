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
        return {
            **raw_result,
            "schema_version": 1,
            "run_id": str(run_id),
            "created_at": created_at.isoformat(),
            "config": config,
            "engine": {"name": config.get("engine", "python"), "amp": True},
            "model": {"id": "mortal-v4-20240308"},
            "hardware": {"device": raw_result.get("device")},
            "candidates": raw_result.get("summaries", []),
            "gpu_telemetry": gpu_telemetry,
            "warnings": [],
        }

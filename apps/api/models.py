from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hand: str = Field(min_length=1, max_length=64)
    first_tsumo: str = Field(min_length=1, max_length=8)
    dora: str = Field(min_length=1, max_length=8)
    discards: list[str] = Field(min_length=1, max_length=34)
    runs: int = Field(default=1000, ge=1, le=100_000)
    seed: int = Field(default=42, ge=0)
    oya: int = Field(default=0, ge=0, le=3)
    batch_size: int = Field(default=1000, ge=1, le=100_000)
    rayon_threads: int = Field(default=20, ge=1, le=256)
    engine: Literal["python"] = "python"
    strict_comparison: bool = True

    @field_validator("discards")
    @classmethod
    def validate_discards(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values if value.strip()]
        if not cleaned:
            raise ValueError("at least one discard candidate is required")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("discard candidates must be unique")
        return cleaned


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    discard: str
    games: int
    errors: int
    avg_rank: float
    avg_point: float


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: UUID
    status: Literal["queued", "running", "completed", "failed", "cancelled"]
    created_at: datetime
    updated_at: datetime
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error: str | None = None


class CapabilityResponse(BaseModel):
    platform: str
    python: str
    cuda_available: bool
    cuda_required: bool
    torch_version: str | None = None
    cuda_version: str | None = None
    gpu_name: str | None = None
    cuda_error: str | None = None
    nvidia_smi_available: bool
    model_exists: bool
    model_path: str
    libriichi_exists: bool
    recommended_engine: str
    data_dir: str

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ROUND_VALUES = tuple(f"{wind}{number}" for wind in "ESW" for number in range(1, 5))
DecisionContract = Literal["stable_advantage_v2", "legacy_amp_v1"]


def _count_tiles(notation: str) -> int:
    """Validate the compact notation sufficiently for request-shape checks.

    The simulation service remains the authoritative parser, but rejecting a
    13/14-tile mismatch here keeps malformed browser requests out of workers.
    """
    numbers = ""
    count = 0
    for char in notation.strip():
        if char in "0123456789":
            numbers += char
        elif char in "mps":
            if not numbers or any(number not in "0123456789" for number in numbers):
                raise ValueError("invalid suited tile notation")
            count += len(numbers)
            numbers = ""
        elif char == "z":
            if not numbers or any(number not in "1234567" for number in numbers):
                raise ValueError("invalid honor tile notation")
            count += len(numbers)
            numbers = ""
        elif char in "ESWNPFC":
            if numbers:
                raise ValueError("honor tiles cannot follow unfinished digits")
            count += 1
        else:
            raise ValueError("invalid tile notation")
    if numbers:
        raise ValueError("tile notation has trailing digits")
    return count


class RelativeScoresInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    self: int = 25_000
    shimocha: int = 25_000
    toimen: int = 25_000

    @field_validator("self", "shimocha", "toimen")
    @classmethod
    def validate_score(cls, value: int) -> int:
        if value < 0 or value % 100:
            raise ValueError("scores must be non-negative multiples of 100")
        return value


class DiscardCandidate(BaseModel):
    """One first-discard action.

    A riichi action is distinct from an ordinary discard even when both use the
    same tile, so historical requests may contain both variants.
    """

    model_config = ConfigDict(extra="forbid")

    tile: str = Field(min_length=1, max_length=8)
    riichi: bool = False

    @field_validator("tile")
    @classmethod
    def validate_tile(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("discard tile must not be empty")
        return cleaned

    @property
    def candidate_id(self) -> str:
        return f"riichi:{self.tile}" if self.riichi else self.tile


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hand: str = Field(min_length=1, max_length=64, description="14 tiles; the last tile is the first tsumo")
    # Kept only to replay and extend schema-v2 records created by the former
    # 13-tile-plus-tsumo input. New public requests omit this field.
    first_tsumo: str | None = Field(default=None, min_length=1, max_length=8, json_schema_extra={"deprecated": True})
    dora: str = Field(min_length=1, max_length=8)
    discards: list[DiscardCandidate] = Field(min_length=1, max_length=34)
    runs: int = Field(default=1000, ge=1, le=100_000)
    seed: int = Field(default=42, ge=0)
    round: Literal[
        "E1", "E2", "E3", "E4",
        "S1", "S2", "S3", "S4",
        "W1", "W2", "W3", "W4",
    ] = "E1"
    honba: int = Field(default=0, ge=0, le=99)
    kyotaku: int = Field(default=0, ge=0, le=99)
    scores: RelativeScoresInput = Field(default_factory=RelativeScoresInput)
    batch_size: int = Field(default=1000, ge=1, le=100_000)
    model_id: str = Field(default="mortal-v4-20240308", min_length=1, max_length=80)
    rayon_threads: int = Field(default=20, ge=1, le=256)
    engine: Literal["python", "lite"] = "lite"
    decision_contract: DecisionContract = "stable_advantage_v2"
    strict_comparison: bool = True
    replay_of: UUID | None = None
    expected_trace_hash: str | None = None

    @model_validator(mode="after")
    def validate_resolved_scores(self) -> "RunRequest":
        expected_tiles = 13 if self.first_tsumo is not None else 14
        actual_tiles = _count_tiles(self.hand)
        if actual_tiles != expected_tiles:
            suffix = " with legacy first_tsumo" if self.first_tsumo is not None else ""
            raise ValueError(f"hand must contain exactly {expected_tiles} tiles{suffix}; got {actual_tiles}")
        kamicha = 100_000 - self.kyotaku * 1_000 - self.scores.self - self.scores.shimocha - self.scores.toimen
        if kamicha < 0 or kamicha % 100:
            raise ValueError("derived kamicha score must be a non-negative multiple of 100")
        if self.engine == "lite":
            if self.decision_contract != "stable_advantage_v2":
                raise ValueError("Formal Lite supports only stable_advantage_v2")
            if self.batch_size != 1000:
                raise ValueError("stable_advantage_v2 requires batch_size=1000")
        elif self.decision_contract != "legacy_amp_v1":
            raise ValueError("the Python development engine supports only legacy_amp_v1")
        return self

    @field_validator("discards", mode="before")
    @classmethod
    def coerce_discards(cls, values: Any) -> list[Any]:
        if isinstance(values, str):
            values = values.split(",")
        if not isinstance(values, list):
            raise ValueError("discard candidates must be a list")
        cleaned: list[Any] = []
        for value in values:
            if isinstance(value, str):
                if value.strip():
                    cleaned.append({"tile": value.strip(), "riichi": False})
            elif isinstance(value, dict):
                cleaned.append(value)
            else:
                raise ValueError("discard candidates must be strings or objects")
        return cleaned

    @field_validator("discards")
    @classmethod
    def validate_discards(cls, values: list[DiscardCandidate]) -> list[DiscardCandidate]:
        if not values:
            raise ValueError("at least one discard candidate is required")
        ids = [value.candidate_id for value in values]
        if len(set(ids)) != len(ids):
            raise ValueError("discard candidates must be unique by tile and riichi mode")
        return values


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    discard: str
    games: int
    errors: int
    avg_rank: float
    avg_point: float


class ReplayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate: str = Field(min_length=1, max_length=8)
    seed: int | list[int]
    expected_trace_hash: str | None = None


class ExtensionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    additional_runs: int = Field(ge=1, le=100_000)
    batch_size: int | None = Field(default=None, ge=1, le=100_000)


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: UUID
    status: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
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
    compute_capability: str | None = None
    cuda_error: str | None = None
    nvidia_smi_available: bool
    model_exists: bool
    model_path: str
    libriichi_exists: bool
    recommended_engine: str
    supported_decision_contracts: list[str]
    runtime_build_id: str | None = None
    runtime_artifact_sha256: str | None = None
    formal_lite_ready: bool
    data_dir: str

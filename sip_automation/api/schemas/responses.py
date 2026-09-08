from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class CalculationParametersRequest(BaseModel):
    """
    Optional runtime parameter overrides for SIP calculations.
    Any parameters provided here override the defaults from sip_metrics.yaml.
    All fields are optional.
    """
    
    # Selected calculation period
    quarter: Literal["Q2", "Q3", "Q4"] | None = None

    # Maximum SIP rules
    q2_max_sip_multiplier: float | None = None
    q3_max_sip_multiplier: float | None = None
    q4_high_target_multiplier: float | None = None
    q4_high_target_threshold: float | None = None
    
    # Target phasing (BP Revenue and GP/DOP)
    target_q2_multiplier: float | None = None
    target_q3_multiplier: float | None = None
    target_q4_multiplier: float | None = None
    
    # Commission rate weights
    revenue_incentive_weight: float | None = None
    gp_incentive_weight: float | None = None
    base_band_weight: float | None = None
    surge_band_weight: float | None = None
    base_achievement_band: float | None = None
    surge_achievement_band: float | None = None
    special_surge_revenue_cap: float | None = None
    special_surge_gp_floor: float | None = None
    special_surge_gp_cap: float | None = None
    
    # Commission earning thresholds
    base_commission_threshold: float | None = None
    surge_commission_cap: float | None = None
    special_surge_threshold: float | None = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class RawLoadResponse(BaseModel):
    run_id: UUID
    status: Literal["completed"] = "completed"
    rows_loaded: dict[str, int] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    detail: str
    run_id: UUID | None = None

class PipelineStageResponse(BaseModel):
    run_id: UUID
    stage: str
    status: str    

class MetricPipelineResponse(BaseModel):
    run_id: UUID
    stage: Literal["sip_calculations"] = "sip_calculations"
    status: Literal["completed"] = "completed"

    calculated_rows: int
    published_rows: int

    enabled_roles: list[str] = Field(
        default_factory=list
    )

    role_row_counts: dict[str, int] = Field(
        default_factory=dict
    )

    output_directory: str
    output_files: dict[str, str] = Field(
        default_factory=dict
    )


class ResultsResponse(BaseModel):
    run_id: UUID
    role: str
    row_count: int

    columns: list[str] = Field(default_factory=list)
    curated_columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)


class CurrentRunResponse(BaseModel):
    run_id: UUID | None = None
    enabled_roles: list[str] = Field(default_factory=list)
    role_row_counts: dict[str, int] = Field(default_factory=dict)

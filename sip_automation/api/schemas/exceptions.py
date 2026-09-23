from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PrecomputeExceptionRequest(BaseModel):
    """
    Create/update payload for a precompute exception.

    Each amount field is optional and has its own independent percentage +
    direction. Direction is required whenever that field's amount is set
    (see build_adjustment_dataset).
    """

    employee_id: str
    employee_name: str | None = None
    category: str | None = None

    bp_fy26_rev: float | None = None
    bp_fy26_rev_percentage: float | None = None
    bp_fy26_rev_direction: Literal["+", "-"] | None = None

    bp_fy26_gp: float | None = None
    bp_fy26_gp_percentage: float | None = None
    bp_fy26_gp_direction: Literal["+", "-"] | None = None

    ytd_fy26_rev: float | None = None
    ytd_fy26_rev_percentage: float | None = None
    ytd_fy26_rev_direction: Literal["+", "-"] | None = None

    ytd_fy26_gp: float | None = None
    ytd_fy26_gp_percentage: float | None = None
    ytd_fy26_gp_direction: Literal["+", "-"] | None = None

    months_eligible_override: float | None = None
    ytd_actual_revenue_override: float | None = None
    ytd_actual_gp_dop_override: float | None = None
    target_sales_rev_direct_override: float | None = None
    target_gp_dop_direct_override: float | None = None

    bp_sga: float | None = None
    ytd_sga: float | None = None

    changed_by: str | None = None

    @field_validator("months_eligible_override")
    @classmethod
    def _validate_months_eligible_override(cls, value: float | None) -> float | None:
        if value is None:
            return value
        if value != int(value) or value < 1 or value > 12:
            raise ValueError(
                "months_eligible_override must be a whole number between 1 and 12."
            )
        return value


class PrecomputeExceptionResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: str | None = None
    category: str | None = None

    bp_fy26_rev: float | None = None
    bp_fy26_rev_percentage: float | None = None
    bp_fy26_rev_direction: Literal["+", "-"] | None = None

    bp_fy26_gp: float | None = None
    bp_fy26_gp_percentage: float | None = None
    bp_fy26_gp_direction: Literal["+", "-"] | None = None

    ytd_fy26_rev: float | None = None
    ytd_fy26_rev_percentage: float | None = None
    ytd_fy26_rev_direction: Literal["+", "-"] | None = None

    ytd_fy26_gp: float | None = None
    ytd_fy26_gp_percentage: float | None = None
    ytd_fy26_gp_direction: Literal["+", "-"] | None = None

    months_eligible_override: float | None = None
    ytd_actual_revenue_override: float | None = None
    ytd_actual_gp_dop_override: float | None = None
    target_sales_rev_direct_override: float | None = None
    target_gp_dop_direct_override: float | None = None

    bp_sga: float | None = None
    ytd_sga: float | None = None

    created_at: str
    updated_at: str
    updated_by: str | None = None


class PrecomputeExceptionListResponse(BaseModel):
    exceptions: list[PrecomputeExceptionResponse] = Field(
        default_factory=list
    )


class PrecomputeExceptionCategoriesResponse(BaseModel):
    categories: list[str] = Field(default_factory=list)


class PrecomputeExceptionUploadRowError(BaseModel):
    row_number: int
    employee_id: str | None = None
    error: str


class PrecomputeExceptionUploadResponse(BaseModel):
    total_rows: int
    saved_count: int
    error_count: int
    errors: list[PrecomputeExceptionUploadRowError] = Field(
        default_factory=list
    )

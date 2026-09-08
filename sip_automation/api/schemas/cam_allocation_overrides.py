from __future__ import annotations

from pydantic import BaseModel, Field


class CAMAllocationOverrideRequest(BaseModel):
    cam_id: str
    employee_name: str | None = None
    division_node: str | None = None
    allocation_pct_rev: float | None = None
    allocation_pct_gp: float | None = None
    note: str | None = None
    changed_by: str | None = None


class CAMAllocationOverrideResponse(BaseModel):
    id: str
    cam_id: str
    employee_name: str | None = None
    division_node: str | None = None
    allocation_pct_rev: float | None = None
    allocation_pct_gp: float | None = None
    note: str | None = None
    created_at: str
    updated_at: str
    updated_by: str | None = None


class CAMAllocationOverrideListResponse(BaseModel):
    overrides: list[CAMAllocationOverrideResponse] = Field(default_factory=list)

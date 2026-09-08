from __future__ import annotations

from pydantic import BaseModel, Field


class DataCorrectionRequest(BaseModel):
    employee_id: str
    employee_name: str | None = None
    source_file: str
    column_name: str
    new_value: str
    note: str | None = None
    changed_by: str | None = None


class DataCorrectionResponse(BaseModel):
    id: str
    employee_id: str
    employee_name: str | None = None
    source_file: str
    column_name: str
    new_value: str
    note: str | None = None
    created_at: str
    updated_at: str
    updated_by: str | None = None


class DataCorrectionListResponse(BaseModel):
    corrections: list[DataCorrectionResponse] = Field(default_factory=list)


class DataCorrectionFilesResponse(BaseModel):
    files: dict[str, str] = Field(default_factory=dict)

"""
File-backed store for "Data Corrections".

Finance/HR-entered, per-employee raw data corrections that persist across
pipeline runs. Stored as a plain YAML file (same pattern as
precompute_exceptions.py) so no database schema is required.

Each correction overrides one cell in one source file for a given employee:
    employee_id + source_file + column_name → new_value

Corrections are applied during canonical_pipeline.run_table(), right after
the raw table is read from Postgres and before any canonical transforms run.
This means all downstream calculations automatically see the corrected values.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from sip_automation.core.exceptions import (
    PrecomputeExceptionNotFoundError as _NotFoundError,
    PrecomputeExceptionValidationError as _ValidationError,
)

# project_root/sip_automation/core/data_corrections.py
#   parents[0] = core
#   parents[1] = sip_automation
#   parents[2] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CORRECTIONS_PATH = PROJECT_ROOT / "data" / "data_corrections.yaml"

# Logical table names mapped to human-readable labels for the UI.
ALLOWED_SOURCE_FILES: dict[str, str] = {
    "employee": "Employee",
    "bp": "BP",
    "sales": "Sales",
    "nacs_guarantee": "NACS Guarantee",
    "ytd_payments": "YTD Payments",
    "bdm": "BDM",
}

# Each raw table identifies an employee under a different column name
# (set by that table's config/tables/*.yaml direct_mappings) - there is no
# single "Employee ID" column across all of them. bp uses a "shared"
# column, bdm uses its own bdm_id concept entirely.
EMPLOYEE_ID_COLUMN_BY_SOURCE_FILE: dict[str, str] = {
    "employee": "employee_id",
    "bp": "employee_id_only_for_shared",
    "sales": "employee_id",
    "nacs_guarantee": "employee_id",
    "ytd_payments": "employee_id",
    "bdm": "bdm_id",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class DataCorrection:
    id: str
    employee_id: str
    employee_name: str | None
    source_file: str
    column_name: str
    new_value: str
    note: str | None
    created_at: str
    updated_at: str
    updated_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DataCorrectionsStore:
    """File-backed CRUD store for data corrections."""

    def __init__(self, path: Path = DEFAULT_CORRECTIONS_PATH) -> None:
        self.path = path

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def list(self) -> list[DataCorrection]:
        return [self._from_dict(row) for row in self._read_raw()]

    def get(self, correction_id: str) -> DataCorrection:
        for correction in self.list():
            if correction.id == correction_id:
                return correction
        raise _NotFoundError(f"Data correction not found: {correction_id!r}.")

    def create(
        self,
        payload: dict[str, Any],
        *,
        changed_by: str | None = None,
    ) -> DataCorrection:
        employee_id = str(payload.get("employee_id") or "").strip()
        if not employee_id:
            raise _ValidationError("employee_id is required.")

        source_file = str(payload.get("source_file") or "").strip()
        if source_file not in ALLOWED_SOURCE_FILES:
            raise _ValidationError(
                f"source_file must be one of: {', '.join(ALLOWED_SOURCE_FILES)}."
            )

        column_name = str(payload.get("column_name") or "").strip()
        if not column_name:
            raise _ValidationError("column_name is required.")

        new_value = str(payload.get("new_value") or "").strip()
        if new_value == "":
            raise _ValidationError("new_value is required.")

        now = _now()
        correction = DataCorrection(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            employee_name=payload.get("employee_name") or None,
            source_file=source_file,
            column_name=column_name,
            new_value=new_value,
            note=payload.get("note") or None,
            created_at=now,
            updated_at=now,
            updated_by=changed_by,
        )

        rows = self._read_raw()
        rows.append(correction.to_dict())
        self._write_raw(rows)
        return correction

    def update(
        self,
        correction_id: str,
        payload: dict[str, Any],
        *,
        changed_by: str | None = None,
    ) -> DataCorrection:
        rows = self._read_raw()
        idx = next(
            (i for i, r in enumerate(rows) if r.get("id") == correction_id),
            None,
        )
        if idx is None:
            raise _NotFoundError(f"Data correction not found: {correction_id!r}.")

        updated = dict(rows[idx])

        if "employee_id" in payload:
            v = str(payload["employee_id"] or "").strip()
            if not v:
                raise _ValidationError("employee_id is required.")
            updated["employee_id"] = v

        if "source_file" in payload:
            v = str(payload["source_file"] or "").strip()
            if v not in ALLOWED_SOURCE_FILES:
                raise _ValidationError(
                    f"source_file must be one of: {', '.join(ALLOWED_SOURCE_FILES)}."
                )
            updated["source_file"] = v

        if "column_name" in payload:
            v = str(payload["column_name"] or "").strip()
            if not v:
                raise _ValidationError("column_name is required.")
            updated["column_name"] = v

        if "new_value" in payload:
            v = str(payload["new_value"] or "").strip()
            if v == "":
                raise _ValidationError("new_value is required.")
            updated["new_value"] = v

        for field in ("employee_name", "note"):
            if field in payload:
                updated[field] = payload[field] or None

        updated["updated_at"] = _now()
        updated["updated_by"] = changed_by
        rows[idx] = updated
        self._write_raw(rows)
        return self._from_dict(updated)

    def delete(self, correction_id: str, *, changed_by: str | None = None) -> None:
        rows = self._read_raw()
        if not any(r.get("id") == correction_id for r in rows):
            raise _NotFoundError(f"Data correction not found: {correction_id!r}.")
        self._write_raw([r for r in rows if r.get("id") != correction_id])

    # ------------------------------------------------------------------ #
    # YAML persistence (atomic write)
    # ------------------------------------------------------------------ #

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            content = yaml.safe_load(fh) or {}
        rows = content.get("corrections", [])
        if not isinstance(rows, list):
            return []
        return [dict(r) for r in rows]

    def _write_raw(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {"corrections": rows},
                fh,
                sort_keys=False,
                default_flow_style=False,
            )
        tmp.replace(self.path)

    @staticmethod
    def _from_dict(row: dict[str, Any]) -> DataCorrection:
        return DataCorrection(
            id=str(row.get("id")),
            employee_id=str(row.get("employee_id")),
            employee_name=row.get("employee_name"),
            source_file=str(row.get("source_file")),
            column_name=str(row.get("column_name")),
            new_value=str(row.get("new_value")),
            note=row.get("note"),
            created_at=str(row.get("created_at")),
            updated_at=str(row.get("updated_at")),
            updated_by=row.get("updated_by"),
        )


# ------------------------------------------------------------------ #
# Pipeline helper — called by canonical_pipeline.run_table()
# ------------------------------------------------------------------ #

def apply_corrections_to_dataframe(
    df: pd.DataFrame,
    corrections: list[DataCorrection],
    logical_table_name: str,
) -> pd.DataFrame:
    """
    Apply any matching data corrections to a raw DataFrame in-place (copy).

    Matches by that table's employee-id raw column (see
    EMPLOYEE_ID_COLUMN_BY_SOURCE_FILE - it differs per table, there is no
    single "Employee ID" column across all raw tables). If the specified
    column does not exist in df, that correction is silently skipped.
    """
    matching = [c for c in corrections if c.source_file == logical_table_name]
    if not matching:
        return df

    emp_id_column = EMPLOYEE_ID_COLUMN_BY_SOURCE_FILE.get(logical_table_name)
    if emp_id_column is None or emp_id_column not in df.columns:
        return df

    df = df.copy()
    emp_col = df[emp_id_column].astype(str).str.strip().str.upper()

    for correction in matching:
        emp_id = str(correction.employee_id).strip().upper()
        mask = emp_col == emp_id
        if not mask.any():
            continue
        if correction.column_name not in df.columns:
            continue

        # new_value is always a string (see DataCorrection), but raw
        # columns loaded from Postgres keep their real dtype (int64,
        # float64, etc.) - assigning a string directly into a numeric
        # column raises a pandas dtype error. Coerce to match where
        # possible; otherwise widen the column to object so the
        # assignment can't crash the whole canonical pipeline run.
        column_dtype = df[correction.column_name].dtype
        value: Any = correction.new_value

        if pd.api.types.is_numeric_dtype(column_dtype):
            try:
                value = pd.to_numeric(correction.new_value)
            except (TypeError, ValueError):
                df[correction.column_name] = df[correction.column_name].astype(object)
        elif pd.api.types.is_bool_dtype(column_dtype):
            value = str(correction.new_value).strip().lower() in ("true", "1", "yes")

        df.loc[mask, correction.column_name] = value

    return df

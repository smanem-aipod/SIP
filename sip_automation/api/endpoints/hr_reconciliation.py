from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from sip_automation.core.hr_exclusions import HRExclusionsStore

# sip_automation/api/endpoints/ → go up 4 levels to project root (sip-automation/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

router = APIRouter()

# ------------------------------------------------------------------ #
# Reconciliation config
# ------------------------------------------------------------------ #

_KEY_COL = "Employee ID"
_NAME_COL = "Full Name"
_HIRE_DATE_COL = "Hire Date"

_TRACK_COLS = [
    "Job Profile",
    "SIP/ CIP or Other Bonus Plan",
    "Bonus Plans - Plan Details",
    "Target Bonus - Percent",
    "Target Bonus Amount",
    "Compensation Grade Profile",
    "Compensation Grade",
    "Total Base Pay - Currency",
    "FTE %",
    "Supervisory Organization - ID",
    "Supervisory Organization",
    "L1 Leader",
    "L2 Leader",
    "L3 Leader",
    "Cost Center - ID",
    "Company - ID",
    "Active (Yes/No)",
    "On Leave",
    "Retired (Yes/No)",
]

_FIELD_DETAILS: dict[str, tuple[str, str]] = {
    "Job Profile": ("Job", "Job Profile changed"),
    "SIP/ CIP or Other Bonus Plan": ("Bonus Plan", "Bonus Plan changed"),
    "Bonus Plans - Plan Details": ("Bonus Plan", "Bonus Plan details changed"),
    "Target Bonus - Percent": ("Compensation", "Target Bonus % changed"),
    "Target Bonus Amount": ("Compensation", "Target Bonus Amount changed"),
    "Compensation Grade Profile": ("Compensation", "Compensation Grade Profile changed"),
    "Compensation Grade": ("Compensation", "Compensation Grade changed"),
    "Total Base Pay - Currency": ("Compensation", "Base Pay Currency changed"),
    "FTE %": ("Employment", "FTE % changed"),
    "Supervisory Organization - ID": ("Organization", "Supervisory Organization ID changed"),
    "Supervisory Organization": ("Organization", "Supervisory Organization changed"),
    "L1 Leader": ("Manager", "L1 Leader changed"),
    "L2 Leader": ("Manager", "L2 Leader changed"),
    "L3 Leader": ("Manager", "L3 Leader changed"),
    "Cost Center - ID": ("Organization", "Cost Center changed"),
    "Company - ID": ("Organization", "Company changed"),
    "Active (Yes/No)": ("Employment Status", "Active status changed"),
    "On Leave": ("Employment Status", "Leave status changed"),
    "Retired (Yes/No)": ("Employment Status", "Retirement status changed"),
}


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _normalize_header(value: str) -> str:
    """
    Loosen column-name matching so minor formatting differences between
    an HR export and _KEY_COL/_TRACK_COLS (extra/missing spaces, dashes
    vs no dashes, case) don't silently drop a tracked field from
    reconciliation. Collapses everything to lowercase alphanumerics.
    """
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _resolve_column(
    expected_name: str,
    actual_columns: list[str],
) -> str | None:
    """Find the real column in actual_columns matching expected_name,
    tolerating spacing/dash/case differences. Returns None if no match."""
    normalized_expected = _normalize_header(expected_name)
    for actual in actual_columns:
        if _normalize_header(actual) == normalized_expected:
            return actual
    return None


def _get_exclusions_store() -> HRExclusionsStore:
    return HRExclusionsStore(_PROJECT_ROOT / "data" / "hr_exclusions.yaml")


def _load_roster(upload: UploadFile) -> pd.DataFrame:
    content = upload.file.read()
    name = (upload.filename or "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content))
    else:
        df = pd.read_excel(io.BytesIO(content))

    key_col = _resolve_column(_KEY_COL, list(df.columns))
    if key_col is None:
        raise ValueError(
            f"Could not find an '{_KEY_COL}' column. "
            f"Available columns: {list(df.columns)}"
        )

    if key_col != _KEY_COL:
        df = df.rename(columns={key_col: _KEY_COL})

    df[_KEY_COL] = df[_KEY_COL].astype(str).str.strip()
    return df.drop_duplicates(subset=_KEY_COL, keep="last")


def _values_equal(v1, v2) -> bool:
    if pd.isna(v1) and pd.isna(v2):
        return True
    return v1 == v2


def _run_reconciliation(q1: pd.DataFrame, q2: pd.DataFrame) -> dict:
    changes: list[dict] = []

    # New joiners vs. rehires/movements - resolve Hire Date in both files so
    # "not present in Q1" isn't automatically treated as a brand-new hire.
    # An employee whose Hire Date predates what we've already seen in Q1
    # reappeared for some other reason (movement, reactivation, ID change),
    # not because they were just hired.
    q1_hire_col = _resolve_column(_HIRE_DATE_COL, list(q1.columns))
    q2_hire_col = _resolve_column(_HIRE_DATE_COL, list(q2.columns))

    hire_date_cutoff = None
    if q1_hire_col is not None:
        q1_hire_dates = pd.to_datetime(q1[q1_hire_col], errors="coerce")
        if q1_hire_dates.notna().any():
            hire_date_cutoff = q1_hire_dates.max()

    unmatched_hire_date_columns: list[str] = []
    if q1_hire_col is None or q2_hire_col is None:
        unmatched_hire_date_columns.append(_HIRE_DATE_COL)

    for _, row in q2.loc[~q2[_KEY_COL].isin(q1[_KEY_COL])].iterrows():
        hire_date_value = (
            pd.to_datetime(row.get(q2_hire_col), errors="coerce")
            if q2_hire_col is not None
            else None
        )

        is_new_employee = (
            q2_hire_col is not None
            and hire_date_cutoff is not None
            and pd.notna(hire_date_value)
            and hire_date_value > hire_date_cutoff
        )

        if q2_hire_col is None or hire_date_cutoff is None:
            # Can't evaluate Hire Date at all - fall back to the old
            # presence-based behavior rather than silently miscategorizing.
            change_type = "New Joiner"
            reason = "Employee exists in Q2 but not in Q1"
        elif is_new_employee:
            change_type = "New Joiner"
            reason = "Employee exists in Q2 but not in Q1, and Hire Date is after Q1's latest known hire"
        else:
            change_type = "Rehire / Movement"
            reason = "Employee exists in Q2 but not in Q1, but Hire Date predates Q1 - not a new hire"

        changes.append({
            "employee_id": row[_KEY_COL],
            "employee_name": str(row.get(_NAME_COL, "") or ""),
            "change_type": change_type,
            "field": "Employment Status",
            "metric": change_type,
            "reason": reason,
            "q1_value": "Not Present",
            "q2_value": "Present",
        })

    # Leavers
    for _, row in q1.loc[~q1[_KEY_COL].isin(q2[_KEY_COL])].iterrows():
        changes.append({
            "employee_id": row[_KEY_COL],
            "employee_name": str(row.get(_NAME_COL, "") or ""),
            "change_type": "Leaver",
            "field": "Employment Status",
            "metric": "Leaver",
            "reason": "Employee exists in Q1 but not in Q2",
            "q1_value": "Present",
            "q2_value": "Not Present",
        })

    # Field changes for common employees - resolve each tracked column's
    # real header in both files individually (they can differ in spacing/
    # case/dashes between exports without being a "missing column").
    common_ids = set(q1[_KEY_COL]).intersection(set(q2[_KEY_COL]))
    q1c = q1[q1[_KEY_COL].isin(common_ids)].set_index(_KEY_COL)
    q2c = q2[q2[_KEY_COL].isin(common_ids)].set_index(_KEY_COL)

    resolved_pairs: list[tuple[str, str, str]] = []  # (tracked_name, q1_col, q2_col)
    unmatched_columns: list[str] = []

    for tracked_name in _TRACK_COLS:
        q1_col = _resolve_column(tracked_name, list(q1c.columns))
        q2_col = _resolve_column(tracked_name, list(q2c.columns))
        if q1_col is None or q2_col is None:
            unmatched_columns.append(tracked_name)
            continue
        resolved_pairs.append((tracked_name, q1_col, q2_col))

    for emp_id in common_ids:
        q1_row = q1c.loc[emp_id]
        q2_row = q2c.loc[emp_id]
        full_name = str(q2_row.get(_NAME_COL, "") or "")
        for tracked_name, q1_col, q2_col in resolved_pairs:
            v1, v2 = q1_row[q1_col], q2_row[q2_col]
            if _values_equal(v1, v2):
                continue
            metric, reason = _FIELD_DETAILS.get(tracked_name, ("Other", f"{tracked_name} changed"))
            changes.append({
                "employee_id": emp_id,
                "employee_name": full_name,
                "change_type": "Field Change",
                "field": tracked_name,
                "metric": metric,
                "reason": reason,
                "q1_value": "" if pd.isna(v1) else str(v1),
                "q2_value": "" if pd.isna(v2) else str(v2),
            })

    new_joiners = sum(1 for c in changes if c["change_type"] == "New Joiner")
    rehires_movements = sum(1 for c in changes if c["change_type"] == "Rehire / Movement")
    leavers = sum(1 for c in changes if c["change_type"] == "Leaver")
    changed_ids = {c["employee_id"] for c in changes if c["change_type"] == "Field Change"}

    return {
        "changes": changes,
        "summary": {
            "new_joiners": new_joiners,
            "rehires_movements": rehires_movements,
            "leavers": leavers,
            "field_changes": len(changed_ids),
            "employees_affected": len({c["employee_id"] for c in changes}),
        },
        # Surfaced so a mismatched export column shows up as a visible
        # warning instead of silently vanishing from the diff, like
        # DEF-019 (Cost Center changes not being picked up).
        "unmatched_columns": unmatched_columns + unmatched_hire_date_columns,
    }


# ------------------------------------------------------------------ #
# Pydantic models
# ------------------------------------------------------------------ #

class ExclusionsRequest(BaseModel):
    excluded_employee_ids: list[str]


class ExclusionsResponse(BaseModel):
    excluded_employee_ids: list[str]


# ------------------------------------------------------------------ #
# Endpoints
# ------------------------------------------------------------------ #

@router.post("/compare", tags=["hr-reconciliation"])
async def compare_hr_files(
    q1_file: Annotated[UploadFile, File()],
    q2_file: Annotated[UploadFile, File()],
) -> dict:
    """Compare two HR roster files and return the list of differences."""
    try:
        q1 = _load_roster(q1_file)
        q2 = _load_roster(q2_file)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to read HR files: {exc}") from exc

    return _run_reconciliation(q1, q2)


@router.get("/exclusions", response_model=ExclusionsResponse, tags=["hr-reconciliation"])
def get_exclusions() -> ExclusionsResponse:
    """Return the currently persisted list of excluded employee IDs."""
    store = _get_exclusions_store()
    return ExclusionsResponse(excluded_employee_ids=store.load())


@router.post("/exclusions", response_model=ExclusionsResponse, tags=["hr-reconciliation"])
def save_exclusions(body: ExclusionsRequest) -> ExclusionsResponse:
    """Overwrite the persisted exclusion list."""
    store = _get_exclusions_store()
    # Normalize to uppercase so this always matches the employee_id casing
    # used in canonical data (e.g. "EMP_100") regardless of how the caller
    # typed it - a case mismatch here silently excludes no one.
    cleaned = sorted(set(str(i).strip().upper() for i in body.excluded_employee_ids if str(i).strip()))
    store.save(cleaned)
    return ExclusionsResponse(excluded_employee_ids=cleaned)

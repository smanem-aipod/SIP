from __future__ import annotations

import io
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

def _get_exclusions_store() -> HRExclusionsStore:
    return HRExclusionsStore(_PROJECT_ROOT / "data" / "hr_exclusions.yaml")


def _load_roster(upload: UploadFile) -> pd.DataFrame:
    content = upload.file.read()
    name = (upload.filename or "").lower()
    if name.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(content), dtype={_KEY_COL: str})
    else:
        df = pd.read_excel(io.BytesIO(content), dtype={_KEY_COL: str})
    df[_KEY_COL] = df[_KEY_COL].astype(str).str.strip()
    return df.drop_duplicates(subset=_KEY_COL, keep="last")


def _values_equal(v1, v2) -> bool:
    if pd.isna(v1) and pd.isna(v2):
        return True
    return v1 == v2


def _run_reconciliation(q1: pd.DataFrame, q2: pd.DataFrame) -> dict:
    changes: list[dict] = []

    # New joiners
    for _, row in q2.loc[~q2[_KEY_COL].isin(q1[_KEY_COL])].iterrows():
        changes.append({
            "employee_id": row[_KEY_COL],
            "employee_name": str(row.get(_NAME_COL, "") or ""),
            "change_type": "New Joiner",
            "field": "Employment Status",
            "metric": "New Joiner",
            "reason": "Employee exists in Q2 but not in Q1",
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

    # Field changes for common employees
    common_ids = set(q1[_KEY_COL]).intersection(set(q2[_KEY_COL]))
    q1c = q1[q1[_KEY_COL].isin(common_ids)].set_index(_KEY_COL)
    q2c = q2[q2[_KEY_COL].isin(common_ids)].set_index(_KEY_COL)
    available_cols = [c for c in _TRACK_COLS if c in q1c.columns and c in q2c.columns]

    for emp_id in common_ids:
        q1_row = q1c.loc[emp_id]
        q2_row = q2c.loc[emp_id]
        full_name = str(q2_row.get(_NAME_COL, "") or "")
        for field in available_cols:
            v1, v2 = q1_row[field], q2_row[field]
            if _values_equal(v1, v2):
                continue
            metric, reason = _FIELD_DETAILS.get(field, ("Other", f"{field} changed"))
            changes.append({
                "employee_id": emp_id,
                "employee_name": full_name,
                "change_type": "Field Change",
                "field": field,
                "metric": metric,
                "reason": reason,
                "q1_value": "" if pd.isna(v1) else str(v1),
                "q2_value": "" if pd.isna(v2) else str(v2),
            })

    new_joiners = sum(1 for c in changes if c["change_type"] == "New Joiner")
    leavers = sum(1 for c in changes if c["change_type"] == "Leaver")
    changed_ids = {c["employee_id"] for c in changes if c["change_type"] == "Field Change"}

    return {
        "changes": changes,
        "summary": {
            "new_joiners": new_joiners,
            "leavers": leavers,
            "field_changes": len(changed_ids),
            "employees_affected": len({c["employee_id"] for c in changes}),
        },
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

    if _KEY_COL not in q1.columns or _KEY_COL not in q2.columns:
        raise HTTPException(
            status_code=422,
            detail=f"Both files must contain an '{_KEY_COL}' column.",
        )

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
    cleaned = sorted(set(str(i).strip() for i in body.excluded_employee_ids if str(i).strip()))
    store.save(cleaned)
    return ExclusionsResponse(excluded_employee_ids=cleaned)

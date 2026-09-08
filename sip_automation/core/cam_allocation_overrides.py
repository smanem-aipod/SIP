"""
File-backed store for CAM allocation overrides.

Finance can override the computed allocation ratio for a specific CAM
employee (optionally scoped to a division) before calculations run.
The override replaces the auto-computed ratio:

    __allocation_ratio = cam_bp_target / total_division_bp_target

Stored as plain YAML (same atomic-write pattern as precompute_exceptions.py).
Applied inside WeightedAllocationSumOperation in aggregate.py.
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

# project_root/sip_automation/core/cam_allocation_overrides.py
#   parents[0] = core
#   parents[1] = sip_automation
#   parents[2] = project root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_CAM_OVERRIDES_PATH = (
    PROJECT_ROOT / "data" / "cam_allocation_overrides.yaml"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _validate_pct(field: str, value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError) as exc:
        raise _ValidationError(f"{field} must be numeric, got {value!r}.") from exc
    if not (0.0 <= v <= 100.0):
        raise _ValidationError(f"{field} must be between 0 and 100.")
    return v


@dataclass
class CAMAllocationOverride:
    id: str
    cam_id: str
    employee_name: str | None
    division_node: str | None      # None = applies to all divisions
    allocation_pct_rev: float | None   # 0–100
    allocation_pct_gp: float | None    # 0–100
    note: str | None
    created_at: str
    updated_at: str
    updated_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CAMAllocationOverridesStore:
    """File-backed CRUD store for CAM allocation overrides."""

    def __init__(self, path: Path = DEFAULT_CAM_OVERRIDES_PATH) -> None:
        self.path = path

    def list(self) -> list[CAMAllocationOverride]:
        return [self._from_dict(r) for r in self._read_raw()]

    def get(self, override_id: str) -> CAMAllocationOverride:
        for o in self.list():
            if o.id == override_id:
                return o
        raise _NotFoundError(f"CAM allocation override not found: {override_id!r}.")

    def create(
        self,
        payload: dict[str, Any],
        *,
        changed_by: str | None = None,
    ) -> CAMAllocationOverride:
        cam_id = str(payload.get("cam_id") or "").strip()
        if not cam_id:
            raise _ValidationError("cam_id is required.")

        pct_rev = _validate_pct("allocation_pct_rev", payload.get("allocation_pct_rev"))
        pct_gp = _validate_pct("allocation_pct_gp", payload.get("allocation_pct_gp"))

        if pct_rev is None and pct_gp is None:
            raise _ValidationError(
                "At least one of allocation_pct_rev or allocation_pct_gp is required."
            )

        now = _now()
        override = CAMAllocationOverride(
            id=str(uuid.uuid4()),
            cam_id=cam_id,
            employee_name=payload.get("employee_name") or None,
            division_node=str(payload.get("division_node") or "").strip() or None,
            allocation_pct_rev=pct_rev,
            allocation_pct_gp=pct_gp,
            note=payload.get("note") or None,
            created_at=now,
            updated_at=now,
            updated_by=changed_by,
        )

        rows = self._read_raw()
        rows.append(override.to_dict())
        self._write_raw(rows)
        return override

    def update(
        self,
        override_id: str,
        payload: dict[str, Any],
        *,
        changed_by: str | None = None,
    ) -> CAMAllocationOverride:
        rows = self._read_raw()
        idx = next(
            (i for i, r in enumerate(rows) if r.get("id") == override_id),
            None,
        )
        if idx is None:
            raise _NotFoundError(f"CAM allocation override not found: {override_id!r}.")

        updated = dict(rows[idx])

        if "cam_id" in payload:
            v = str(payload["cam_id"] or "").strip()
            if not v:
                raise _ValidationError("cam_id is required.")
            updated["cam_id"] = v

        if "employee_name" in payload:
            updated["employee_name"] = payload["employee_name"] or None

        if "division_node" in payload:
            updated["division_node"] = (
                str(payload["division_node"] or "").strip() or None
            )

        merged_rev = payload.get("allocation_pct_rev", updated.get("allocation_pct_rev"))
        merged_gp = payload.get("allocation_pct_gp", updated.get("allocation_pct_gp"))
        pct_rev = _validate_pct("allocation_pct_rev", merged_rev)
        pct_gp = _validate_pct("allocation_pct_gp", merged_gp)

        if pct_rev is None and pct_gp is None:
            raise _ValidationError(
                "At least one of allocation_pct_rev or allocation_pct_gp is required."
            )

        updated["allocation_pct_rev"] = pct_rev
        updated["allocation_pct_gp"] = pct_gp

        if "note" in payload:
            updated["note"] = payload["note"] or None

        updated["updated_at"] = _now()
        updated["updated_by"] = changed_by
        rows[idx] = updated
        self._write_raw(rows)
        return self._from_dict(updated)

    def delete(self, override_id: str, *, changed_by: str | None = None) -> None:
        rows = self._read_raw()
        if not any(r.get("id") == override_id for r in rows):
            raise _NotFoundError(f"CAM allocation override not found: {override_id!r}.")
        self._write_raw([r for r in rows if r.get("id") != override_id])

    # ------------------------------------------------------------------ #
    # YAML persistence
    # ------------------------------------------------------------------ #

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        with self.path.open("r", encoding="utf-8") as fh:
            content = yaml.safe_load(fh) or {}
        rows = content.get("overrides", [])
        return [dict(r) for r in rows] if isinstance(rows, list) else []

    def _write_raw(self, rows: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(
                {"overrides": rows},
                fh,
                sort_keys=False,
                default_flow_style=False,
            )
        tmp.replace(self.path)

    @staticmethod
    def _from_dict(row: dict[str, Any]) -> CAMAllocationOverride:
        return CAMAllocationOverride(
            id=str(row.get("id")),
            cam_id=str(row.get("cam_id")),
            employee_name=row.get("employee_name"),
            division_node=row.get("division_node"),
            allocation_pct_rev=row.get("allocation_pct_rev"),
            allocation_pct_gp=row.get("allocation_pct_gp"),
            note=row.get("note"),
            created_at=str(row.get("created_at")),
            updated_at=str(row.get("updated_at")),
            updated_by=row.get("updated_by"),
        )


# ------------------------------------------------------------------ #
# Pipeline helper
# ------------------------------------------------------------------ #

def build_cam_overrides_dataframe(
    overrides: list[CAMAllocationOverride],
) -> pd.DataFrame | None:
    """Convert override list to a DataFrame for the calculation engine."""
    if not overrides:
        return None
    records = [
        {
            "cam_id": o.cam_id,
            "division_node": o.division_node,
            "allocation_pct_rev": o.allocation_pct_rev,
            "allocation_pct_gp": o.allocation_pct_gp,
        }
        for o in overrides
    ]
    return pd.DataFrame.from_records(records)

"""
File-backed store for "Precompute Exceptions".

Finance-entered, per-employee revenue/GP exceptions that persist across
pipeline runs (unlike raw.*/canonical.* tables, which are rebuilt from the
uploaded Excel files on every run). Stored as a plain YAML file so no
database schema/migration is required; every create/update/delete is
recorded as one line per changed field in a plain-text audit log.

Exceptions flow into the SIP calculation through the "precompute_exceptions"
calculation dataset (see CalculationContext) and the lookup operations on
bp_rev_adjustments / bp_gp_adjustments / rev_adjustments / gp_adjustments in
config/calculations/sip_metrics.yaml.

Each of the 4 amount fields (BP FY26 Rev/GP, YTD FY26 Rev/GP) has its own
independent percentage + direction:

    magnitude = amount * percentage / 100   if a percentage is entered
    magnitude = amount                       otherwise

    adjustment = +magnitude if direction == "+" else -magnitude

Direction is required for any field that has an amount entered.

Two additional fields, months_eligible_override and
ytd_actual_revenue_override, are complete overrides (not adjustments):
when entered, they replace the calculated "# Months Eligible" /
"YTD Actual in Regional Currency (Revenue)" value outright for that
employee (see the months_eligible / ytd_actual_revenue if_else metrics in
config/calculations/sip_metrics.yaml). Left blank, the calculated value is
used unchanged. ytd_actual_gp_dop_override works the same way for
"YTD Actual in Regional Currency (GP/DOP)".

Two more fields, bp_sga and ytd_sga, are subtracted (not overridden) when
entered: bp_sga from bp_gp_dop_2026_direct ("Target GP/DOP DIRECT") and
ytd_sga from ytd_actual_gp_dop ("YTD Actual in Regional Currency
(GP/DOP)"), before any other adjustments/overrides are applied - see the
bp_gp_dop_2026_direct_after_sga / ytd_actual_gp_dop_after_sga metrics in
config/calculations/sip_metrics.yaml. Left blank, they have no effect
(default 0).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from sip_automation.core.exceptions import (
    PrecomputeExceptionNotFoundError,
    PrecomputeExceptionValidationError,
)

# precompute_exceptions.py is located at:
#
# project_root/src/sip_automation/core/precompute_exceptions.py
#
# parents[0] = core
# parents[1] = sip_automation
# parents[2] = src
# parents[3] = project root

PROJECT_ROOT = Path(__file__).resolve().parents[3]

DEFAULT_EXCEPTIONS_PATH = (
    PROJECT_ROOT / "data" / "precompute_exceptions.yaml"
)

DEFAULT_AUDIT_LOG_PATH = (
    PROJECT_ROOT / "logs" / "precompute_exceptions_audit.log"
)

PRECOMPUTE_EXCEPTION_CATEGORIES: tuple[str, ...] = (
    "Responsible for two groups",
    "Product Level targets",
    "Leave Case",
    "CS-IS Shipto Addition",
)

AMOUNT_FIELDS: tuple[str, ...] = (
    "bp_fy26_rev",
    "bp_fy26_gp",
    "ytd_fy26_rev",
    "ytd_fy26_gp",
)

# Maps each admin-entered amount field to the calculation-engine
# adjustment column it feeds (see sip_metrics.yaml lookup metrics).
ADJUSTMENT_COLUMN_BY_AMOUNT_FIELD: dict[str, str] = {
    "bp_fy26_rev": "bp_rev_adjustments",
    "bp_fy26_gp": "bp_gp_adjustments",
    "ytd_fy26_rev": "rev_adjustments",
    "ytd_fy26_gp": "gp_adjustments",
}

ADJUSTMENT_COLUMNS: tuple[str, ...] = tuple(
    ADJUSTMENT_COLUMN_BY_AMOUNT_FIELD.values()
)

# Complete-override fields: the admin-entered value replaces the
# calculated metric outright (column name == field name, no
# percentage/direction combination like the adjustment fields above).
OVERRIDE_FIELDS: tuple[str, ...] = (
    "months_eligible_override",
    "ytd_actual_revenue_override",
    "ytd_actual_gp_dop_override",
)

# Subtraction fields: when entered, subtracted from bp_gp_dop_2026_direct /
# ytd_actual_gp_dop before other adjustments (column name == field name,
# same as OVERRIDE_FIELDS, but summed across an employee's rows like
# ADJUSTMENT_COLUMNS rather than "first non-null").
SGA_FIELDS: tuple[str, ...] = (
    "bp_sga",
    "ytd_sga",
)


def _percentage_field(amount_field: str) -> str:
    return f"{amount_field}_percentage"


def _direction_field(amount_field: str) -> str:
    return f"{amount_field}_direction"


PERCENTAGE_FIELDS: tuple[str, ...] = tuple(
    _percentage_field(field) for field in AMOUNT_FIELDS
)

DIRECTION_FIELDS: tuple[str, ...] = tuple(
    _direction_field(field) for field in AMOUNT_FIELDS
)

_ALLOWED_DIRECTIONS = ("+", "-")

_EDITABLE_FIELDS: tuple[str, ...] = (
    "employee_id",
    "employee_name",
    "category",
    *AMOUNT_FIELDS,
    *PERCENTAGE_FIELDS,
    *DIRECTION_FIELDS,
    *OVERRIDE_FIELDS,
    *SGA_FIELDS,
)

# Public alias - used by the bulk upload endpoint to recognize/normalize
# spreadsheet column headers against the same field set as create()/update().
EXCEPTION_UPLOAD_FIELDS: tuple[str, ...] = _EDITABLE_FIELDS


@dataclass
class PrecomputeException:
    """
    One admin-entered exception row.

    Each amount field has its own independent percentage + direction,
    e.g. bp_fy26_rev / bp_fy26_rev_percentage / bp_fy26_rev_direction.
    """

    id: str
    employee_id: str
    employee_name: str | None
    category: str | None

    bp_fy26_rev: float | None
    bp_fy26_rev_percentage: float | None
    bp_fy26_rev_direction: str | None

    bp_fy26_gp: float | None
    bp_fy26_gp_percentage: float | None
    bp_fy26_gp_direction: str | None

    ytd_fy26_rev: float | None
    ytd_fy26_rev_percentage: float | None
    ytd_fy26_rev_direction: str | None

    ytd_fy26_gp: float | None
    ytd_fy26_gp_percentage: float | None
    ytd_fy26_gp_direction: str | None

    months_eligible_override: float | None
    ytd_actual_revenue_override: float | None
    ytd_actual_gp_dop_override: float | None

    bp_sga: float | None
    ytd_sga: float | None

    created_at: str
    updated_at: str
    updated_by: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_audit_logger: logging.Logger | None = None


def _get_audit_logger() -> logging.Logger:
    """
    Simple, human-readable rotating log file, kept separate from the
    structured JSON application log so changes are easy to eyeball.
    """

    global _audit_logger

    if _audit_logger is not None:
        return _audit_logger

    DEFAULT_AUDIT_LOG_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit_logger = logging.getLogger(
        "precompute_exceptions_audit"
    )
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False

    if not audit_logger.handlers:
        handler = RotatingFileHandler(
            filename=DEFAULT_AUDIT_LOG_PATH,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )

        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s")
        )

        audit_logger.addHandler(handler)

    _audit_logger = audit_logger

    return audit_logger


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    )


def _validate_percentage(
    field_name: str,
    value: Any,
) -> float | None:
    if value in (None, "", "null"):
        return None

    try:
        numeric_value = float(value)
    except (TypeError, ValueError) as exc:
        raise PrecomputeExceptionValidationError(
            f"{field_name} must be numeric, got {value!r}."
        ) from exc

    if numeric_value < 0:
        raise PrecomputeExceptionValidationError(
            f"{field_name} cannot be negative."
        )

    return numeric_value


def _validate_direction(
    field_name: str,
    value: Any,
) -> str | None:
    if value in (None, "", "null"):
        return None

    text_value = str(value).strip()

    if text_value not in _ALLOWED_DIRECTIONS:
        raise PrecomputeExceptionValidationError(
            f"{field_name} must be '+' or '-' (or left blank)."
        )

    return text_value


def _validate_amount(
    field_name: str,
    value: Any,
) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise PrecomputeExceptionValidationError(
            f"{field_name} must be numeric, got {value!r}."
        ) from exc


def _validate_amount_group(
    payload: dict[str, Any],
) -> dict[str, float | str | None]:
    """
    Validate the amount/percentage/direction triple for every amount field.

    Direction is required whenever that field's amount is provided.
    """

    values: dict[str, float | str | None] = {}

    for amount_field in AMOUNT_FIELDS:
        percentage_field = _percentage_field(amount_field)
        direction_field = _direction_field(amount_field)

        amount = _validate_amount(
            amount_field,
            payload.get(amount_field),
        )
        percentage = _validate_percentage(
            percentage_field,
            payload.get(percentage_field),
        )
        direction = _validate_direction(
            direction_field,
            payload.get(direction_field),
        )

        if amount is not None and direction is None:
            raise PrecomputeExceptionValidationError(
                f"{direction_field} ('+' or '-') is required "
                f"when {amount_field} is entered."
            )

        values[amount_field] = amount
        values[percentage_field] = percentage
        values[direction_field] = direction

    return values


def _validate_override_group(
    payload: dict[str, Any],
) -> dict[str, float | None]:
    """
    Validate the two complete-override fields. Unlike the amount fields,
    these have no percentage/direction: the entered value replaces the
    calculated metric outright.
    """

    return {
        field_name: _validate_amount(
            field_name,
            payload.get(field_name),
        )
        for field_name in OVERRIDE_FIELDS
    }


def _validate_sga_group(
    payload: dict[str, Any],
) -> dict[str, float | None]:
    """
    Validate the two SG&A subtraction fields - plain numeric values, no
    percentage/direction.
    """

    return {
        field_name: _validate_amount(
            field_name,
            payload.get(field_name),
        )
        for field_name in SGA_FIELDS
    }


class PrecomputeExceptionsStore:
    """
    File-backed CRUD store for precompute exceptions.
    """

    def __init__(
        self,
        *,
        path: Path = DEFAULT_EXCEPTIONS_PATH,
    ) -> None:
        self.path = path

    def list(self) -> list[PrecomputeException]:
        return [
            self._from_dict(row)
            for row in self._read_raw()
        ]

    def get(
        self,
        exception_id: str,
    ) -> PrecomputeException:
        for exception in self.list():
            if exception.id == exception_id:
                return exception

        raise PrecomputeExceptionNotFoundError(
            f"Precompute exception not found: {exception_id!r}."
        )

    def create(
        self,
        payload: dict[str, Any],
        *,
        changed_by: str | None = None,
    ) -> PrecomputeException:
        employee_id = str(
            payload.get("employee_id") or ""
        ).strip().upper()

        if not employee_id:
            raise PrecomputeExceptionValidationError(
                "employee_id is required."
            )

        amount_group = _validate_amount_group(payload)
        override_group = _validate_override_group(payload)
        sga_group = _validate_sga_group(payload)

        now = _now()

        exception = PrecomputeException(
            id=str(uuid.uuid4()),
            employee_id=employee_id,
            employee_name=(
                payload.get("employee_name") or None
            ),
            category=(
                payload.get("category") or None
            ),
            created_at=now,
            updated_at=now,
            updated_by=changed_by,
            **amount_group,
            **override_group,
            **sga_group,
        )

        rows = self._read_raw()
        rows.append(exception.to_dict())
        self._write_raw(rows)

        _get_audit_logger().info(
            "CREATE | emp_id=%s | category=%s | by=%s",
            exception.employee_id,
            exception.category,
            changed_by or "unknown",
        )

        return exception

    def update(
        self,
        exception_id: str,
        payload: dict[str, Any],
        *,
        changed_by: str | None = None,
    ) -> PrecomputeException:
        rows = self._read_raw()

        target_index = next(
            (
                index
                for index, row in enumerate(rows)
                if row.get("id") == exception_id
            ),
            None,
        )

        if target_index is None:
            raise PrecomputeExceptionNotFoundError(
                f"Precompute exception not found: {exception_id!r}."
            )

        existing = rows[target_index]

        # Validate the full amount/percentage/direction picture using the
        # merged view (existing values overridden by anything supplied in
        # this update), so a partial update can't leave an amount without
        # a direction.
        merged_for_validation = {**existing, **payload}
        validated_amount_group = _validate_amount_group(
            merged_for_validation
        )
        validated_override_group = _validate_override_group(
            merged_for_validation
        )
        validated_sga_group = _validate_sga_group(
            merged_for_validation
        )

        updated = dict(existing)
        audit_logger = _get_audit_logger()

        editable_non_amount_fields = (
            "employee_id",
            "employee_name",
            "category",
        )

        for field_name in editable_non_amount_fields:
            if field_name not in payload:
                continue

            if field_name == "employee_id":
                # Uppercased to match canonical.employee's convention -
                # the lookup join is an exact string match, so a casing
                # mismatch here silently breaks every exception field.
                new_value = str(
                    payload[field_name] or ""
                ).strip().upper()

                if not new_value:
                    raise PrecomputeExceptionValidationError(
                        "employee_id is required."
                    )
            else:
                new_value = payload[field_name] or None

            old_value = existing.get(field_name)

            if old_value != new_value:
                audit_logger.info(
                    "UPDATE | emp_id=%s | field=%s | "
                    "old=%s | new=%s | by=%s",
                    existing.get("employee_id"),
                    field_name,
                    old_value,
                    new_value,
                    changed_by or "unknown",
                )

                updated[field_name] = new_value

        for field_name, new_value in validated_amount_group.items():
            old_value = existing.get(field_name)

            if old_value != new_value:
                audit_logger.info(
                    "UPDATE | emp_id=%s | field=%s | "
                    "old=%s | new=%s | by=%s",
                    existing.get("employee_id"),
                    field_name,
                    old_value,
                    new_value,
                    changed_by or "unknown",
                )

                updated[field_name] = new_value

        for field_name, new_value in validated_override_group.items():
            old_value = existing.get(field_name)

            if old_value != new_value:
                audit_logger.info(
                    "UPDATE | emp_id=%s | field=%s | "
                    "old=%s | new=%s | by=%s",
                    existing.get("employee_id"),
                    field_name,
                    old_value,
                    new_value,
                    changed_by or "unknown",
                )

                updated[field_name] = new_value

        for field_name, new_value in validated_sga_group.items():
            old_value = existing.get(field_name)

            if old_value != new_value:
                audit_logger.info(
                    "UPDATE | emp_id=%s | field=%s | "
                    "old=%s | new=%s | by=%s",
                    existing.get("employee_id"),
                    field_name,
                    old_value,
                    new_value,
                    changed_by or "unknown",
                )

                updated[field_name] = new_value

        updated["updated_at"] = _now()
        updated["updated_by"] = changed_by

        rows[target_index] = updated
        self._write_raw(rows)

        return self._from_dict(updated)

    def replace_all(
        self,
        rows: list[dict[str, Any]],
        *,
        changed_by: str | None = None,
    ) -> tuple[list[PrecomputeException], list[tuple[int, str | None, str]]]:
        """
        Validate every row in `rows` (1-based row_number for error
        reporting). Only rows that pass validation are kept; invalid rows
        are skipped and returned as errors (partial success).

        If no row is valid, the file on disk is NOT modified - the caller
        should treat an empty `saved` list as "reject the whole upload".
        """

        saved: list[PrecomputeException] = []
        errors: list[tuple[int, str | None, str]] = []
        now = _now()

        for index, payload in enumerate(rows, start=1):
            # Callers that pre-filter/re-number rows (e.g. the upload
            # endpoint, which drops rows with an unrecognized metric before
            # they get here) can pass along the original row number under
            # "_row_number" so error messages still point at the right line
            # in the uploaded file.
            row_number = payload.get("_row_number", index)
            raw_employee_id = payload.get("employee_id")
            employee_id = str(raw_employee_id or "").strip().upper()

            try:
                if not employee_id:
                    raise PrecomputeExceptionValidationError(
                        "employee_id is required."
                    )

                amount_group = _validate_amount_group(payload)
                override_group = _validate_override_group(payload)
                sga_group = _validate_sga_group(payload)

            except PrecomputeExceptionValidationError as exc:
                errors.append(
                    (row_number, employee_id or None, str(exc))
                )
                continue

            saved.append(
                PrecomputeException(
                    id=str(uuid.uuid4()),
                    employee_id=employee_id,
                    employee_name=(
                        payload.get("employee_name") or None
                    ),
                    category=(
                        payload.get("category") or None
                    ),
                    created_at=now,
                    updated_at=now,
                    updated_by=changed_by,
                    **amount_group,
                    **override_group,
                    **sga_group,
                )
            )

        if saved:
            self._write_raw([exception.to_dict() for exception in saved])

            audit_logger = _get_audit_logger()

            audit_logger.info(
                "REPLACE_ALL | total=%s | saved=%s | errors=%s | by=%s",
                len(rows),
                len(saved),
                len(errors),
                changed_by or "unknown",
            )

            for exception in saved:
                audit_logger.info(
                    "CREATE | emp_id=%s | category=%s | by=%s",
                    exception.employee_id,
                    exception.category,
                    changed_by or "unknown",
                )

        return saved, errors

    def delete(
        self,
        exception_id: str,
        *,
        changed_by: str | None = None,
    ) -> None:
        rows = self._read_raw()

        target = next(
            (
                row
                for row in rows
                if row.get("id") == exception_id
            ),
            None,
        )

        if target is None:
            raise PrecomputeExceptionNotFoundError(
                f"Precompute exception not found: {exception_id!r}."
            )

        remaining = [
            row
            for row in rows
            if row.get("id") != exception_id
        ]

        self._write_raw(remaining)

        _get_audit_logger().info(
            "DELETE | emp_id=%s | category=%s | by=%s",
            target.get("employee_id"),
            target.get("category"),
            changed_by or "unknown",
        )

    def _read_raw(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        with self.path.open(
            "r",
            encoding="utf-8",
        ) as stream:
            content = yaml.safe_load(stream) or {}

        rows = content.get("exceptions", [])

        if not isinstance(rows, list):
            raise PrecomputeExceptionValidationError(
                f"{self.path} must contain an 'exceptions' list."
            )

        return [dict(row) for row in rows]

    def _write_raw(
        self,
        rows: list[dict[str, Any]],
    ) -> None:
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = self.path.with_suffix(".tmp")

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as stream:
            yaml.safe_dump(
                {"exceptions": rows},
                stream,
                sort_keys=False,
                default_flow_style=False,
            )

        temporary_path.replace(self.path)

    @staticmethod
    def _from_dict(
        row: dict[str, Any],
    ) -> PrecomputeException:
        return PrecomputeException(
            id=str(row.get("id")),
            employee_id=str(row.get("employee_id")),
            employee_name=row.get("employee_name"),
            category=row.get("category"),
            bp_fy26_rev=row.get("bp_fy26_rev"),
            bp_fy26_rev_percentage=row.get("bp_fy26_rev_percentage"),
            bp_fy26_rev_direction=row.get("bp_fy26_rev_direction"),
            bp_fy26_gp=row.get("bp_fy26_gp"),
            bp_fy26_gp_percentage=row.get("bp_fy26_gp_percentage"),
            bp_fy26_gp_direction=row.get("bp_fy26_gp_direction"),
            ytd_fy26_rev=row.get("ytd_fy26_rev"),
            ytd_fy26_rev_percentage=row.get("ytd_fy26_rev_percentage"),
            ytd_fy26_rev_direction=row.get("ytd_fy26_rev_direction"),
            ytd_fy26_gp=row.get("ytd_fy26_gp"),
            ytd_fy26_gp_percentage=row.get("ytd_fy26_gp_percentage"),
            ytd_fy26_gp_direction=row.get("ytd_fy26_gp_direction"),
            months_eligible_override=row.get("months_eligible_override"),
            ytd_actual_revenue_override=row.get(
                "ytd_actual_revenue_override"
            ),
            ytd_actual_gp_dop_override=row.get(
                "ytd_actual_gp_dop_override"
            ),
            bp_sga=row.get("bp_sga"),
            ytd_sga=row.get("ytd_sga"),
            created_at=str(row.get("created_at")),
            updated_at=str(row.get("updated_at")),
            updated_by=row.get("updated_by"),
        )


def build_adjustment_dataset(
    exceptions: list[PrecomputeException],
) -> pd.DataFrame:
    """
    Aggregate precompute exceptions into one row per employee_id with the
    4 adjustment columns the calculation engine looks up: bp_rev_adjustments,
    bp_gp_adjustments, rev_adjustments, gp_adjustments, plus the 2 complete
    override columns: months_eligible_override, ytd_actual_revenue_override.

    Each amount field has its own independent percentage + direction:

        magnitude = amount * percentage / 100   if a percentage is entered
        magnitude = amount                       otherwise

        adjustment = +magnitude if direction == "+" else -magnitude

    The override columns are not adjustments: they are the raw admin-entered
    value, used as-is by the calculation engine's if_else metrics.

    bp_sga / ytd_sga are summed like the adjustment columns (not "first
    non-null" like the overrides), since they represent an amount to
    subtract rather than a value to replace.

    Multiple exception rows for the same employee are summed per adjustment
    column, so an employee with several exceptions (e.g. two different
    categories) still resolves to exactly one row, as required by the
    lookup operation. Override columns instead take the first non-null
    value across that employee's rows.
    """

    summed_columns = (*ADJUSTMENT_COLUMNS, *SGA_FIELDS)
    columns = ["employee_id", *summed_columns, *OVERRIDE_FIELDS]

    if not exceptions:
        return pd.DataFrame(columns=columns)

    records: list[dict[str, Any]] = []

    for exception in exceptions:
        record: dict[str, Any] = {
            "employee_id": exception.employee_id
        }

        for (
            amount_field,
            adjustment_column,
        ) in ADJUSTMENT_COLUMN_BY_AMOUNT_FIELD.items():
            amount = getattr(exception, amount_field)

            if amount is None:
                record[adjustment_column] = None
                continue

            percentage = getattr(
                exception,
                _percentage_field(amount_field),
            )
            direction = getattr(
                exception,
                _direction_field(amount_field),
            )

            magnitude = (
                amount
                if percentage is None
                else amount * percentage / 100.0
            )

            record[adjustment_column] = (
                magnitude
                if direction == "+"
                else -magnitude
            )

        for override_field in OVERRIDE_FIELDS:
            record[override_field] = getattr(
                exception,
                override_field,
            )

        for sga_field in SGA_FIELDS:
            record[sga_field] = getattr(
                exception,
                sga_field,
            )

        records.append(record)

    dataset = pd.DataFrame.from_records(
        records,
        columns=columns,
    )

    for column in ADJUSTMENT_COLUMNS:
        dataset[column] = pd.to_numeric(
            dataset[column],
            errors="coerce",
        )

    for column in SGA_FIELDS:
        dataset[column] = pd.to_numeric(
            dataset[column],
            errors="coerce",
        )

    for column in OVERRIDE_FIELDS:
        dataset[column] = pd.to_numeric(
            dataset[column],
            errors="coerce",
        )

    aggregated_adjustments = (
        dataset
        .groupby(
            "employee_id",
            as_index=False,
        )[list(summed_columns)]
        .sum(min_count=1)
    )

    def _first_non_null(series: pd.Series) -> Any:
        non_null = series.dropna()
        return non_null.iloc[0] if not non_null.empty else None

    aggregated_overrides = (
        dataset
        .groupby(
            "employee_id",
            as_index=False,
        )[list(OVERRIDE_FIELDS)]
        .agg(_first_non_null)
    )

    aggregated = aggregated_adjustments.merge(
        aggregated_overrides,
        on="employee_id",
        how="left",
    )

    return aggregated

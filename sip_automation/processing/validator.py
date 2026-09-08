from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from sip_automation.core.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    rule: str
    message: str
    column: str | None = None
    row_count: int = 0
    sample_indices: tuple[Any, ...] = ()


@dataclass
class ValidationReport:
    logical_table_name: str
    issues: list[ValidationIssue] = field(
        default_factory=list
    )

    @property
    def error_count(self) -> int:
        return sum(
            issue.severity.upper() == "ERROR"
            for issue in self.issues
        )

    @property
    def warning_count(self) -> int:
        return sum(
            issue.severity.upper() == "WARNING"
            for issue in self.issues
        )

    @property
    def is_valid(self) -> bool:
        return self.error_count == 0

    def add_issue(
        self,
        *,
        severity: str,
        rule: str,
        message: str,
        column: str | None = None,
        row_count: int = 0,
        sample_indices: tuple[Any, ...] = (),
    ) -> None:
        self.issues.append(
            ValidationIssue(
                severity=severity.upper(),
                rule=rule,
                message=message,
                column=column,
                row_count=row_count,
                sample_indices=sample_indices,
            )
        )


class TableValidator:
    """
    Validate a canonical DataFrame using table configuration.
    """

    @classmethod
    def validate(
        cls,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        column_config: dict[str, Any],
        validation_config: dict[str, Any] | None,
    ) -> ValidationReport:
        report = ValidationReport(
            logical_table_name=logical_table_name
        )

        config = validation_config or {}

        cls._validate_required_columns(
            dataframe,
            column_config=column_config,
            validation_config=config,
            report=report,
        )

        cls._validate_nullability(
            dataframe,
            column_config=column_config,
            report=report,
        )

        cls._validate_uniqueness(
            dataframe,
            validation_config=config,
            report=report,
        )

        cls._validate_composite_uniqueness(
            dataframe,
            validation_config=config,
            report=report,
        )

        cls._validate_accepted_values(
            dataframe,
            validation_config=config,
            report=report,
        )

        cls._validate_regex(
            dataframe,
            validation_config=config,
            report=report,
        )

        cls._validate_ranges(
            dataframe,
            validation_config=config,
            report=report,
        )

        cls._validate_date_rules(
            dataframe,
            validation_config=config,
            report=report,
        )

        logger.info(
            "table_validation_completed",
            logical_table_name=logical_table_name,
            valid=report.is_valid,
            error_count=report.error_count,
            warning_count=report.warning_count,
            row_count=len(dataframe),
        )

        return report

    @staticmethod
    def _validate_required_columns(
        dataframe: pd.DataFrame,
        *,
        column_config: dict[str, Any],
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        required_from_validation = set(
            validation_config.get(
                "required_columns",
                [],
            )
        )

        required_from_columns = {
            column_name
            for column_name, definition
            in column_config.items()
            if isinstance(definition, dict)
            and definition.get("nullable") is False
        }

        required_columns = (
            required_from_validation
            | required_from_columns
        )

        missing = sorted(
            required_columns - set(dataframe.columns)
        )

        if missing:
            report.add_issue(
                severity="ERROR",
                rule="required_columns",
                message=f"Missing required columns: {missing}",
            )

    @staticmethod
    def _validate_nullability(
        dataframe: pd.DataFrame,
        *,
        column_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        for column_name, definition in (
            column_config.items()
        ):
            if column_name not in dataframe.columns:
                continue

            if not isinstance(definition, dict):
                continue

            if definition.get("nullable", True):
                continue

            invalid_mask = dataframe[
                column_name
            ].isna()

            count = int(invalid_mask.sum())

            if count:
                report.add_issue(
                    severity="ERROR",
                    rule="not_null",
                    column=column_name,
                    row_count=count,
                    sample_indices=tuple(
                        dataframe.index[
                            invalid_mask
                        ][:5].tolist()
                    ),
                    message=(
                        f"Column {column_name!r} contains "
                        f"{count} null values."
                    ),
                )

    @staticmethod
    def _validate_uniqueness(
        dataframe: pd.DataFrame,
        *,
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        for column_name in validation_config.get(
            "unique",
            [],
        ):
            if column_name not in dataframe.columns:
                continue

            duplicate_mask = (
                dataframe[column_name].notna()
                & dataframe[column_name].duplicated(
                    keep=False
                )
            )

            count = int(duplicate_mask.sum())

            if count:
                report.add_issue(
                    severity="ERROR",
                    rule="unique",
                    column=column_name,
                    row_count=count,
                    sample_indices=tuple(
                        dataframe.index[
                            duplicate_mask
                        ][:5].tolist()
                    ),
                    message=(
                        f"Column {column_name!r} contains "
                        f"{count} rows with duplicate values."
                    ),
                )

    @staticmethod
    def _validate_composite_uniqueness(
        dataframe: pd.DataFrame,
        *,
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        rules = validation_config.get(
            "composite_unique",
            [],
        )

        for rule in rules:
            if not isinstance(rule, dict):
                continue

            columns = rule.get("columns", [])
            severity = str(
                rule.get("severity", "ERROR")
            ).upper()

            missing = [
                column
                for column in columns
                if column not in dataframe.columns
            ]

            if missing:
                continue

            duplicate_mask = dataframe.duplicated(
                subset=columns,
                keep=False,
            )

            count = int(duplicate_mask.sum())

            if count:
                report.add_issue(
                    severity=severity,
                    rule="composite_unique",
                    row_count=count,
                    sample_indices=tuple(
                        dataframe.index[
                            duplicate_mask
                        ][:5].tolist()
                    ),
                    message=(
                        f"Composite key {columns} contains "
                        f"{count} duplicate rows."
                    ),
                )

    @staticmethod
    def _validate_accepted_values(
        dataframe: pd.DataFrame,
        *,
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        rules = validation_config.get(
            "accepted_values",
            {},
        )

        for column_name, allowed_values in rules.items():
            if column_name not in dataframe.columns:
                continue

            invalid_mask = (
                dataframe[column_name].notna()
                & ~dataframe[column_name].isin(
                    allowed_values
                )
            )

            count = int(invalid_mask.sum())

            if count:
                report.add_issue(
                    severity="ERROR",
                    rule="accepted_values",
                    column=column_name,
                    row_count=count,
                    sample_indices=tuple(
                        dataframe.index[
                            invalid_mask
                        ][:5].tolist()
                    ),
                    message=(
                        f"Column {column_name!r} contains "
                        f"{count} values outside "
                        f"{allowed_values}."
                    ),
                )

    @staticmethod
    def _validate_regex(
        dataframe: pd.DataFrame,
        *,
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        rules = validation_config.get(
            "regex",
            {},
        )

        for column_name, pattern in rules.items():
            if column_name not in dataframe.columns:
                continue

            values = dataframe[column_name]
            non_null = values.notna()

            matches = (
                values.astype("string")
                .str.fullmatch(
                    str(pattern),
                    na=True,
                )
            )

            invalid_mask = non_null & ~matches

            count = int(invalid_mask.sum())

            if count:
                report.add_issue(
                    severity="ERROR",
                    rule="regex",
                    column=column_name,
                    row_count=count,
                    sample_indices=tuple(
                        dataframe.index[
                            invalid_mask
                        ][:5].tolist()
                    ),
                    message=(
                        f"Column {column_name!r} contains "
                        f"{count} values that do not match "
                        f"{pattern!r}."
                    ),
                )

    @staticmethod
    def _validate_ranges(
        dataframe: pd.DataFrame,
        *,
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        rules = validation_config.get(
            "ranges",
            {},
        )

        for column_name, rule in rules.items():
            if (
                column_name not in dataframe.columns
                or not isinstance(rule, dict)
            ):
                continue

            values = pd.to_numeric(
                dataframe[column_name],
                errors="coerce",
            )

            if (
                "min" in rule
                and rule["min"] is not None
            ):
                invalid_mask = (
                    values.notna()
                    & (values < rule["min"])
                )

                count = int(invalid_mask.sum())

                if count:
                    report.add_issue(
                        severity="ERROR",
                        rule="minimum",
                        column=column_name,
                        row_count=count,
                        message=(
                            f"Column {column_name!r} contains "
                            f"{count} values below "
                            f"{rule['min']}."
                        ),
                    )

            if (
                "max" in rule
                and rule["max"] is not None
            ):
                invalid_mask = (
                    values.notna()
                    & (values > rule["max"])
                )

                count = int(invalid_mask.sum())

                if count:
                    report.add_issue(
                        severity="ERROR",
                        rule="maximum",
                        column=column_name,
                        row_count=count,
                        message=(
                            f"Column {column_name!r} contains "
                            f"{count} values above "
                            f"{rule['max']}."
                        ),
                    )

    @staticmethod
    def _validate_date_rules(
        dataframe: pd.DataFrame,
        *,
        validation_config: dict[str, Any],
        report: ValidationReport,
    ) -> None:
        rules = validation_config.get(
            "date_rules",
            {},
        )

        for column_name, rule in rules.items():
            if (
                column_name not in dataframe.columns
                or not isinstance(rule, dict)
            ):
                continue

            comparison_column = rule.get(
                "greater_than_or_equal_to"
            )

            if (
                comparison_column
                and comparison_column
                in dataframe.columns
            ):
                left = pd.to_datetime(
                    dataframe[column_name],
                    errors="coerce",
                )

                right = pd.to_datetime(
                    dataframe[comparison_column],
                    errors="coerce",
                )

                invalid_mask = (
                    left.notna()
                    & right.notna()
                    & (left < right)
                )

                count = int(invalid_mask.sum())

                if count:
                    report.add_issue(
                        severity="ERROR",
                        rule="date_order",
                        column=column_name,
                        row_count=count,
                        message=(
                            f"{count} rows have "
                            f"{column_name!r} before "
                            f"{comparison_column!r}."
                        ),
                    )
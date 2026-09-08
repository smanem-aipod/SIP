from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from sip_automation.core.exceptions import ColumnMappingError
from sip_automation.core.logging import get_logger
from sip_automation.core.run_context import RunContext


logger = get_logger(__name__)


@dataclass(frozen=True)
class ResolvedColumn:
    raw_column_name: str
    source_column_name: str
    required: bool


class SourceMapper:
    """
    Map provider-specific source columns into stable raw-table columns.

    This mapper does not perform datatype conversion or business
    calculations. It only resolves configured aliases and attaches
    configured metadata values.
    """

    @classmethod
    def map_to_raw(
        cls,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        table_config: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        if not isinstance(dataframe, pd.DataFrame):
            raise ColumnMappingError(
                f"Source mapper expected a DataFrame for "
                f"{logical_table_name!r}."
            )

        source_to_raw = table_config.get("source_to_raw")

        if not isinstance(source_to_raw, dict):
            raise ColumnMappingError(
                f"Table {logical_table_name!r} does not define "
                f"source_to_raw configuration."
            )

        mapping_config = source_to_raw.get("mappings")

        if not isinstance(mapping_config, dict):
            raise ColumnMappingError(
                f"Table {logical_table_name!r} must define "
                f"source_to_raw.mappings."
            )

        normalized_frame, normalized_to_original = (
            cls._normalize_dataframe_headers(dataframe)
        )

        resolved_columns = cls._resolve_columns(
            mapping_config=mapping_config,
            normalized_to_original=normalized_to_original,
            logical_table_name=logical_table_name,
        )

        raw_frame = pd.DataFrame(
            index=normalized_frame.index
        )

        for resolved in resolved_columns:
            normalized_source_name = cls.normalize_header(
                resolved.source_column_name
            )

            raw_frame[resolved.raw_column_name] = (
                normalized_frame[normalized_source_name]
            )

        generated_values = source_to_raw.get(
            "generated_values",
            {},
        )

        cls._apply_generated_values(
            raw_frame,
            generated_values=generated_values,
            context=context,
        )

        raw_frame["pipeline_run_id"] = str(context.run_id)

        logger.info(
            "source_columns_mapped_to_raw",
            logical_table_name=logical_table_name,
            source_column_count=len(dataframe.columns),
            mapped_column_count=len(raw_frame.columns),
            row_count=len(raw_frame),
        )

        return raw_frame

    @classmethod
    def _resolve_columns(
        cls,
        *,
        mapping_config: dict[str, Any],
        normalized_to_original: dict[str, str],
        logical_table_name: str,
    ) -> list[ResolvedColumn]:
        resolved_columns: list[ResolvedColumn] = []
        missing_required: list[str] = []

        used_source_columns: dict[str, str] = {}

        for raw_column_name, definition in mapping_config.items():
            if not isinstance(definition, dict):
                raise ColumnMappingError(
                    f"Mapping definition for {raw_column_name!r} in "
                    f"{logical_table_name!r} must be an object."
                )

            aliases = definition.get("aliases", [])
            required = bool(definition.get("required", False))

            if isinstance(aliases, str):
                aliases = [aliases]

            if not isinstance(aliases, list) or not aliases:
                raise ColumnMappingError(
                    f"Mapping {raw_column_name!r} in "
                    f"{logical_table_name!r} must define aliases."
                )

            matched_source_column: str | None = None

            for alias in aliases:
                normalized_alias = cls.normalize_header(alias)

                if normalized_alias in normalized_to_original:
                    matched_source_column = (
                        normalized_to_original[normalized_alias]
                    )
                    break

            if matched_source_column is None:
                if required:
                    missing_required.append(
                        f"{raw_column_name} "
                        f"(aliases={aliases})"
                    )

                continue

            normalized_match = cls.normalize_header(
                matched_source_column
            )

            if normalized_match in used_source_columns:
                existing_raw_column = used_source_columns[
                    normalized_match
                ]

                raise ColumnMappingError(
                    f"Source column {matched_source_column!r} was mapped "
                    f"to both {existing_raw_column!r} and "
                    f"{raw_column_name!r} in table "
                    f"{logical_table_name!r}."
                )

            used_source_columns[normalized_match] = (
                raw_column_name
            )

            resolved_columns.append(
                ResolvedColumn(
                    raw_column_name=raw_column_name,
                    source_column_name=matched_source_column,
                    required=required,
                )
            )

        if missing_required:
            available_columns = sorted(
                normalized_to_original.values()
            )

            raise ColumnMappingError(
                f"Required source columns could not be resolved for "
                f"{logical_table_name!r}: {missing_required}. "
                f"Available columns: {available_columns}"
            )

        return resolved_columns

    @classmethod
    def _normalize_dataframe_headers(
        cls,
        dataframe: pd.DataFrame,
    ) -> tuple[pd.DataFrame, dict[str, str]]:
        result = dataframe.copy()

        normalized_headers: list[str] = []
        normalized_to_original: dict[str, str] = {}
        duplicate_headers: list[str] = []

        for original_column in result.columns:
            original_name = str(original_column)
            normalized_name = cls.normalize_header(
                original_name
            )

            if normalized_name in normalized_to_original:
                duplicate_headers.append(original_name)

            normalized_headers.append(normalized_name)
            normalized_to_original[normalized_name] = (
                original_name
            )

        if duplicate_headers:
            raise ColumnMappingError(
                "Source contains duplicate columns after header "
                f"normalization: {duplicate_headers}"
            )

        result.columns = normalized_headers

        return result, normalized_to_original

    @staticmethod
    def normalize_header(value: Any) -> str:
        text = str(value)

        return " ".join(
            text
            .replace("\r", " ")
            .replace("\n", " ")
            .replace("\t", " ")
            .replace("\u00a0", " ")
            .strip()
            .split()
        ).casefold()

    @classmethod
    def _apply_generated_values(
        cls,
        dataframe: pd.DataFrame,
        *,
        generated_values: dict[str, Any],
        context: RunContext,
    ) -> None:
        if not generated_values:
            return

        if not isinstance(generated_values, dict):
            raise ColumnMappingError(
                "source_to_raw.generated_values must be an object."
            )

        for output_column, definition in (
            generated_values.items()
        ):
            if not isinstance(definition, dict):
                dataframe[output_column] = definition
                continue

            if "runtime_parameter" in definition:
                runtime_parameter = definition[
                    "runtime_parameter"
                ]

                dataframe[output_column] = (
                    context.get_parameter(
                        str(runtime_parameter),
                        required=True,
                    )
                )

            elif "constant" in definition:
                dataframe[output_column] = definition[
                    "constant"
                ]

            else:
                raise ColumnMappingError(
                    f"Generated value {output_column!r} must define "
                    f"runtime_parameter or constant."
                )
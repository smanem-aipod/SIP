from __future__ import annotations

import re
import unicodedata
from typing import Any

import pandas as pd

from sip_automation.core.exceptions import DataCleaningError
from sip_automation.core.logging import get_logger


logger = get_logger(__name__)


class DataPreprocessor:
    """
    Apply generic configuration-driven cleaning.

    This component has no knowledge of HR, BP, Sales, Excel, or PostgreSQL.
    """

    @classmethod
    def preprocess(
        cls,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        cleaning_config: dict[str, Any] | None,
    ) -> pd.DataFrame:
        if not isinstance(dataframe, pd.DataFrame):
            raise DataCleaningError(
                f"Preprocessor expected a DataFrame for "
                f"{logical_table_name!r}."
            )

        config = cleaning_config or {}
        result = dataframe.copy()

        try:
            result = cls._remove_empty_business_rows(
                result,
                config,
            )

            result = cls._remove_repeated_header_rows(
                result,
                config,
            )

            if config.get("trim_strings", True):
                result = cls._apply_to_text_columns(
                    result,
                    cls._trim_text,
                )

            if config.get(
                "collapse_internal_whitespace",
                True,
            ):
                result = cls._apply_to_text_columns(
                    result,
                    cls._collapse_whitespace,
                )

            if config.get("normalize_unicode", True):
                result = cls._apply_to_text_columns(
                    result,
                    cls._normalize_unicode,
                )

            if config.get(
                "normalize_empty_strings",
                True,
            ):
                null_markers = config.get(
                    "null_markers",
                    [
                        "",
                        "#N/A",
                        "N/A",
                        "NA",
                        "null",
                        "None",
                        "-",
                    ],
                )

                result = cls._normalize_null_markers(
                    result,
                    null_markers=null_markers,
                )

            result = cls._apply_case_rules(
                result,
                config,
            )

            result = cls._apply_value_mappings(
                result,
                config.get("value_mappings", {}),
            )

        except Exception as exc:
            if isinstance(exc, DataCleaningError):
                raise

            raise DataCleaningError(
                f"Preprocessing failed for "
                f"{logical_table_name!r}."
            ) from exc

        result = result.reset_index(drop=True)

        logger.info(
            "data_preprocessing_completed",
            logical_table_name=logical_table_name,
            row_count=len(result),
            column_count=len(result.columns),
        )

        return result

    @staticmethod
    def _apply_to_text_columns(
        dataframe: pd.DataFrame,
        operation: Any,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        candidate_columns = result.select_dtypes(
            include=["object", "string"],
        ).columns

        for column in candidate_columns:
            result[column] = result[column].map(
                operation
            )

        return result

    @staticmethod
    def _trim_text(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None

        if not isinstance(value, str):
            return value

        return value.strip()

    @staticmethod
    def _collapse_whitespace(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None

        if not isinstance(value, str):
            return value

        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _normalize_unicode(value: Any) -> Any:
        if value is None or pd.isna(value):
            return None

        if not isinstance(value, str):
            return value

        return unicodedata.normalize(
            "NFKC",
            value,
        )

    @classmethod
    def _normalize_null_markers(
        cls,
        dataframe: pd.DataFrame,
        *,
        null_markers: list[Any],
    ) -> pd.DataFrame:
        result = dataframe.copy()

        normalized_markers = {
            cls._normalize_comparison_value(marker)
            for marker in null_markers
        }

        for column in result.columns:
            result[column] = result[column].map(
                lambda value: cls._null_if_marker(
                    value,
                    normalized_markers,
                )
            )

        return result

    @classmethod
    def _null_if_marker(
        cls,
        value: Any,
        normalized_markers: set[str],
    ) -> Any:
        if value is None or pd.isna(value):
            return None

        if not isinstance(value, str):
            return value

        normalized_value = (
            cls._normalize_comparison_value(value)
        )

        if normalized_value in normalized_markers:
            return None

        return value

    @staticmethod
    def _normalize_comparison_value(
        value: Any,
    ) -> str:
        return " ".join(
            str(value)
            .strip()
            .split()
        ).casefold()

    @classmethod
    def _apply_case_rules(
        cls,
        dataframe: pd.DataFrame,
        config: dict[str, Any],
    ) -> pd.DataFrame:
        result = dataframe.copy()

        rules = {
            "uppercase": lambda series: (
                series.astype("string").str.upper()
            ),
            "lowercase": lambda series: (
                series.astype("string").str.lower()
            ),
            "titlecase": lambda series: (
                series.astype("string").str.title()
            ),
        }

        for rule_name, operation in rules.items():
            configured_columns = config.get(
                rule_name,
                [],
            )

            if configured_columns is None:
                continue

            if not isinstance(configured_columns, list):
                raise DataCleaningError(
                    f"Cleaning rule {rule_name!r} must be a list."
                )

            for column in configured_columns:
                if column not in result.columns:
                    raise DataCleaningError(
                        f"Cleaning rule {rule_name!r} references "
                        f"missing column {column!r}."
                    )

                original_nulls = result[column].isna()

                converted = operation(result[column])
                converted = converted.astype(object)
                converted[original_nulls] = None

                result[column] = converted

        return result

    @classmethod
    def _apply_value_mappings(
        cls,
        dataframe: pd.DataFrame,
        mappings: dict[str, Any],
    ) -> pd.DataFrame:
        result = dataframe.copy()

        if not mappings:
            return result

        if not isinstance(mappings, dict):
            raise DataCleaningError(
                "cleaning.value_mappings must be an object."
            )

        for column, value_mapping in mappings.items():
            if column not in result.columns:
                raise DataCleaningError(
                    f"Value mapping references missing column "
                    f"{column!r}."
                )

            if not isinstance(value_mapping, dict):
                raise DataCleaningError(
                    f"Value mapping for {column!r} must be an object."
                )

            normalized_mapping = {
                cls._normalize_comparison_value(key): value
                for key, value in value_mapping.items()
            }

            result[column] = result[column].map(
                lambda value: cls._map_value(
                    value,
                    normalized_mapping,
                )
            )

        return result

    @classmethod
    def _map_value(
        cls,
        value: Any,
        normalized_mapping: dict[str, Any],
    ) -> Any:
        if value is None or pd.isna(value):
            return None

        normalized_value = (
            cls._normalize_comparison_value(value)
        )

        return normalized_mapping.get(
            normalized_value,
            value,
        )
    
    @staticmethod
    def _remove_empty_business_rows(
        dataframe: pd.DataFrame,
        config: dict[str, Any],
    ) -> pd.DataFrame:
        """
        Remove rows where all configured business columns are empty.

        Metadata columns such as pipeline_run_id and record_source should not
        decide whether a row contains business data.
        """

        business_columns = config.get(
            "business_columns",
            [],
        )

        if not business_columns:
            return dataframe

        existing_columns = [
            column
            for column in business_columns
            if column in dataframe.columns
        ]

        if not existing_columns:
            return dataframe

        return dataframe.dropna(
            how="all",
            subset=existing_columns,
        )


    @classmethod
    def _remove_repeated_header_rows(
        cls,
        dataframe: pd.DataFrame,
        config: dict[str, Any],
    ) -> pd.DataFrame:
        """
        Remove repeated header rows embedded inside source data.

        Example:
            reporting_line column contains the literal value
            "Reporting line".
        """

        repeated_header_rules = config.get(
            "repeated_header_rows",
            {},
        )

        if not repeated_header_rules:
            return dataframe

        result = dataframe.copy()
        remove_mask = pd.Series(
            False,
            index=result.index,
        )

        for column_name, header_values in (
            repeated_header_rules.items()
        ):
            if column_name not in result.columns:
                continue

            if isinstance(header_values, str):
                header_values = [header_values]

            normalized_headers = {
                cls._normalize_comparison_value(value)
                for value in header_values
            }

            normalized_column = result[column_name].map(
                lambda value: (
                    None
                    if value is None or pd.isna(value)
                    else cls._normalize_comparison_value(value)
                )
            )

            remove_mask = (
                remove_mask
                | normalized_column.isin(normalized_headers)
            )

        return result.loc[~remove_mask]    
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any
from datetime import date, datetime
import pandas as pd

from sip_automation.core.exceptions import DataTypeConversionError
from sip_automation.core.logging import get_logger


logger = get_logger(__name__)


class DataTypeConverter:
    """
    Convert canonical values into configured datatypes.

    Conversion rules are read entirely from the table YAML contract.
    """

    @classmethod
    def convert(
        cls,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        column_config: dict[str, Any],
    ) -> pd.DataFrame:
        if not isinstance(column_config, dict):
            raise DataTypeConversionError(
                f"Column configuration for "
                f"{logical_table_name!r} must be an object."
            )

        result = dataframe.copy()

        for column_name, definition in (
            column_config.items()
        ):
            if column_name not in result.columns:
                continue

            if not isinstance(definition, dict):
                raise DataTypeConversionError(
                    f"Column definition for {column_name!r} in "
                    f"{logical_table_name!r} must be an object."
                )

            configured_type = definition.get("type")

            if not configured_type:
                raise DataTypeConversionError(
                    f"Column {column_name!r} in "
                    f"{logical_table_name!r} has no configured type."
                )

            try:
                result[column_name] = cls._convert_series(
                    result[column_name],
                    column_name=column_name,
                    data_type=str(configured_type),
                    definition=definition,
                )

            except Exception as exc:
                if isinstance(
                    exc,
                    DataTypeConversionError,
                ):
                    raise

                raise DataTypeConversionError(
                    f"Failed to convert column {column_name!r} "
                    f"to {configured_type!r} in table "
                    f"{logical_table_name!r}."
                ) from exc

        logger.info(
            "datatype_conversion_completed",
            logical_table_name=logical_table_name,
            converted_column_count=sum(
                column in result.columns
                for column in column_config
            ),
            row_count=len(result),
        )

        return result


    @classmethod
    def _convert_series(
        cls,
        series: pd.Series,
        *,
        column_name: str,
        data_type: str,
        definition: dict[str, Any],
    ) -> pd.Series:
        normalized_type = data_type.strip().lower()

        converters = {
            "string": cls._to_string,
            "integer": cls._to_integer,
            "decimal": cls._to_decimal,
            "percentage": cls._to_percentage,
            "date": cls._to_date,
            "timestamp": cls._to_timestamp,
            "boolean": cls._to_boolean,
            "currency_code": cls._to_currency_code,
        }

        converter = converters.get(normalized_type)

        if converter is None:
            raise DataTypeConversionError(
                f"Unsupported configured datatype: "
                f"{data_type!r}"
            )

        # Only these two functions accept column_name.
        if normalized_type in {
            "decimal",
            "percentage",
        }:
            return converter(
                series,
                definition,
                column_name=column_name,
            )

        # All other converters accept only series and definition.
        return converter(
            series,
            definition,
        )

    @staticmethod
    def _to_string(
        series: pd.Series,
        definition: dict[str, Any],
    ) -> pd.Series:
        max_length = definition.get("max_length")

        def convert(value: Any) -> str | None:
            if value is None or pd.isna(value):
                return None

            text = str(value).strip()

            if max_length is not None and len(text) > int(
                max_length
            ):
                raise DataTypeConversionError(
                    f"Value exceeds configured maximum length "
                    f"{max_length}: {text!r}"
                )

            return text

        return series.map(convert)

    @staticmethod
    def _to_integer(
        series: pd.Series,
        definition: dict[str, Any],
    ) -> pd.Series:
        converted = pd.to_numeric(
            series,
            errors="coerce",
        )

        invalid_mask = (
            series.notna()
            & converted.isna()
        )

        if invalid_mask.any():
            sample = series[invalid_mask].head(5).tolist()

            raise DataTypeConversionError(
                f"Invalid integer values: {sample}"
            )

        non_integral_mask = (
            converted.notna()
            & (converted % 1 != 0)
        )

        if non_integral_mask.any():
            sample = (
                converted[non_integral_mask]
                .head(5)
                .tolist()
            )

            raise DataTypeConversionError(
                f"Non-integral values cannot be converted to "
                f"integer: {sample}"
            )

        return converted.astype("Int64")

    @classmethod
    def _to_decimal(
        cls,
        series: pd.Series,
        definition: dict[str, Any],
        *,
        column_name: str,
    ) -> pd.Series:
        precision = definition.get("precision")
        scale = definition.get("scale")

        return series.map(
            lambda value: cls._parse_decimal(
                value,
                precision=precision,
                scale=scale,
                column_name=column_name
            )
        )

    @classmethod
    def _to_percentage(
        cls,
        series: pd.Series,
        definition: dict[str, Any],
        *,
        column_name: str,
    ) -> pd.Series:
        precision = definition.get("precision")
        scale = definition.get("scale")

        def convert(value: Any) -> Decimal | None:
            if value is None or pd.isna(value):
                return None

            text = str(value).strip()
            contains_percent = text.endswith("%")
            text = text.removesuffix("%").strip()

            decimal_value = cls._parse_decimal(
                text,
                precision=None,
                scale=None,
                column_name=column_name,
            )

            if decimal_value is None:
                return None

            if contains_percent:
                decimal_value /= Decimal("100")

            return cls._enforce_decimal_contract(
                decimal_value,
                precision=precision,
                scale=scale,
                column_name=column_name,
            )

        return series.map(convert)

    @staticmethod
    def _to_date(
        series: pd.Series,
        definition: dict[str, Any],
    ) -> pd.Series:
        """
        Convert existing datetime values, text dates, and Excel serial-date
        numbers into Python date objects.
        """

        day_first = bool(
            definition.get("day_first", True)
        )

        result = pd.Series(
            pd.NaT,
            index=series.index,
            dtype="datetime64[ns]",
        )

        non_null_mask = series.notna()

        # Values already parsed by pandas/openpyxl, including:
        # pd.Timestamp, datetime.datetime and datetime.date.
        datetime_mask = (
            non_null_mask
            & series.map(
                lambda value: isinstance(
                    value,
                    (
                        pd.Timestamp,
                        datetime,
                        date,
                    ),
                )
            )
        )

        if datetime_mask.any():
            result.loc[datetime_mask] = pd.to_datetime(
                series.loc[datetime_mask],
                errors="coerce",
            )

        remaining_mask = (
            non_null_mask
            & ~datetime_mask
        )

        numeric_values = pd.to_numeric(
            series.loc[remaining_mask],
            errors="coerce",
        )

        numeric_mask = pd.Series(
            False,
            index=series.index,
        )

        numeric_mask.loc[remaining_mask] = (
            numeric_values.notna()
        )

        if numeric_mask.any():
            result.loc[numeric_mask] = pd.to_datetime(
                pd.to_numeric(
                    series.loc[numeric_mask],
                    errors="coerce",
                ),
                unit="D",
                origin="1899-12-30",
                errors="coerce",
            )

        text_mask = (
            remaining_mask
            & ~numeric_mask
        )

        if text_mask.any():
            result.loc[text_mask] = pd.to_datetime(
                series.loc[text_mask],
                errors="coerce",
                dayfirst=day_first,
            )

        invalid_mask = (
            non_null_mask
            & result.isna()
        )

        if invalid_mask.any():
            sample = (
                series.loc[invalid_mask]
                .head(5)
                .tolist()
            )

            raise DataTypeConversionError(
                f"Invalid date values: {sample}"
            )

        return result.dt.date

    @staticmethod
    def _to_timestamp(
        series: pd.Series,
        definition: dict[str, Any],
    ) -> pd.Series:
        day_first = bool(
            definition.get("day_first", True)
        )

        converted = pd.to_datetime(
            series,
            errors="coerce",
            dayfirst=definition.get("day_first", False)
        )

        invalid_mask = (
            series.notna()
            & converted.isna()
        )

        if invalid_mask.any():
            sample = series[invalid_mask].head(5).tolist()

            raise DataTypeConversionError(
                f"Invalid timestamp values: {sample}"
            )

        return converted

    @staticmethod
    def _to_boolean(
        series: pd.Series,
        definition: dict[str, Any],
    ) -> pd.Series:
        configured_mapping = definition.get(
            "mapping",
            {},
        )

        default_mapping = {
            "true": True,
            "yes": True,
            "y": True,
            "1": True,
            "false": False,
            "no": False,
            "n": False,
            "0": False,
        }

        normalized_mapping = {
            **default_mapping,
            **{
                str(key).strip().casefold(): value
                for key, value in configured_mapping.items()
            },
        }

        def convert(value: Any) -> bool | None:
            if value is None or pd.isna(value):
                return None

            if isinstance(value, bool):
                return value

            normalized = str(value).strip().casefold()

            if normalized not in normalized_mapping:
                raise DataTypeConversionError(
                    f"Invalid boolean value: {value!r}"
                )

            converted_value = normalized_mapping[
                normalized
            ]

            if not isinstance(converted_value, bool):
                raise DataTypeConversionError(
                    f"Boolean mapping returned non-boolean value "
                    f"for {value!r}."
                )

            return converted_value

        return series.map(convert)

    @staticmethod
    def _to_currency_code(
        series: pd.Series,
        definition: dict[str, Any],
    ) -> pd.Series:
        def convert(value: Any) -> str | None:
            if value is None or pd.isna(value):
                return None

            return str(value).strip().upper()

        return series.map(convert)

    @classmethod
    def _parse_decimal(
        cls,
        value: Any,
        *,
        precision: int | None,
        scale: int | None,
        column_name: str,
    ) -> Decimal | None:
        if value is None or pd.isna(value):
            return None

        if isinstance(value, Decimal):
            decimal_value = value
        else:
            text = str(value).strip()

            is_parenthesized_negative = (
                text.startswith("(")
                and text.endswith(")")
            )

            text = re.sub(
                r"[,\s$€£₹]",
                "",
                text,
            )

            if is_parenthesized_negative:
                text = f"-{text[1:-1]}"

            if text == "":
                return None

            try:
                decimal_value = Decimal(text)
            except InvalidOperation as exc:
                raise DataTypeConversionError(
                    f"Invalid decimal value: {value!r}"
                ) from exc

        return cls._enforce_decimal_contract(
            decimal_value,
            precision=precision,
            scale=scale,
            column_name=column_name
        )

    @staticmethod
    def _enforce_decimal_contract(
        value: Decimal,
        *,
        precision: int | None,
        scale: int | None,
        column_name: str,
    ) -> Decimal:
        result = value

        if scale is not None:
            quantizer = Decimal("1").scaleb(
                -int(scale)
            )

            result = result.quantize(quantizer)

        if precision is not None:
            normalized = format(
                result.copy_abs(),
                "f",
            ).replace(".", "").lstrip("0")

            digit_count = len(normalized) or 1

            if digit_count > int(precision):
                raise DataTypeConversionError(
                    f"Column '{column_name}' "
                    f"contains value {result} "
                    f"which exceeds configured precision "
                    f"{precision}."
                )

        return result
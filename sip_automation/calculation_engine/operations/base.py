from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any

import pandas as pd

from sip_automation.calculation_engine.context import (
    CalculationContext,
)


class OperationExecutionError(Exception):
    """
    Raised when a configured calculation operation cannot be executed.
    """


class BaseOperation(ABC):
    """
    Common interface for every calculation operation.

    Operations return a Series aligned to the input DataFrame.
    The calculation engine is responsible for assigning that Series
    to the configured output column.
    """

    operation_name: str

    @abstractmethod
    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        """
        Execute the configured operation.
        """

    @staticmethod
    def require_columns(
        dataframe: pd.DataFrame,
        columns: Iterable[str],
        *,
        dataset_name: str = "working_dataframe",
    ) -> None:
        required_columns = {
            str(column)
            for column in columns
            if column is not None
        }

        missing_columns = sorted(
            required_columns - set(dataframe.columns)
        )

        if missing_columns:
            raise OperationExecutionError(
                f"Dataset {dataset_name!r} is missing required "
                f"columns: {missing_columns}."
            )

    @staticmethod
    def as_series(
        value: Any,
        *,
        index: pd.Index,
        name: str | None = None,
    ) -> pd.Series:
        """
        Convert a scalar or Series into a Series aligned to the given index.
        """

        if isinstance(value, pd.Series):
            result = value.reindex(index)
            result.name = name or result.name
            return result

        return pd.Series(
            value,
            index=index,
            name=name,
        )

    @classmethod
    def resolve_operand(
        cls,
        dataframe: pd.DataFrame,
        operand: Any,
        context: CalculationContext,
    ) -> pd.Series:
        """
        Resolve an operand from configuration.

        Supported formats:

        Column:
            column_name

            or

            column: column_name

        Constant:
            value: 10

        Runtime parameter:
            parameter: fiscal_year

        Bare strings are interpreted as column names. String constants
        must therefore use:

            value: "Some text"
        """

        if isinstance(operand, str):
            cls.require_columns(
                dataframe,
                [operand],
            )

            return dataframe[operand].copy()

        if isinstance(operand, dict):
            if "column" in operand:
                column_name = str(operand["column"])

                cls.require_columns(
                    dataframe,
                    [column_name],
                )

                return dataframe[column_name].copy()

            if "value" in operand:
                return cls.as_series(
                    operand.get("value"),
                    index=dataframe.index,
                )

            if "parameter" in operand:
                parameter_name = str(
                    operand["parameter"]
                )

                parameter_value = context.get_parameter(
                    parameter_name,
                    default=operand.get("default"),
                    required=bool(
                        operand.get("required", False)
                    ),
                )

                return cls.as_series(
                    parameter_value,
                    index=dataframe.index,
                )

            if "static_reference" in operand:
                reference = operand["static_reference"]

                if isinstance(reference, dict):
                    reference = reference.get("path")

                if not reference:
                    raise OperationExecutionError(
                        "static_reference must contain a path."
                    )

                reference_value = (
                    context.get_static_reference(
                        str(reference)
                    )
                )

                return cls.as_series(
                    reference_value,
                    index=dataframe.index,
                )
        if operand is None or isinstance(
            operand,
            (int, float, bool),
        ):
            return cls.as_series(
                operand,
                index=dataframe.index,
            )

        raise OperationExecutionError(
            f"Unsupported operand definition: {operand!r}."
        )

    @classmethod
    def resolve_inputs(
        cls,
        dataframe: pd.DataFrame,
        inputs: Any,
        context: CalculationContext,
    ) -> list[pd.Series]:
        """
        Resolve a list or dictionary of operands.
        """

        if isinstance(inputs, dict):
            operand_definitions = list(inputs.values())

        elif isinstance(inputs, list):
            operand_definitions = inputs

        else:
            raise OperationExecutionError(
                "Operation inputs must be a list or dictionary."
            )

        return [
            cls.resolve_operand(
                dataframe,
                operand,
                context,
            )
            for operand in operand_definitions
        ]

    @staticmethod
    def to_numeric(
        series: pd.Series,
    ) -> pd.Series:
        return pd.to_numeric(
            series,
            errors="coerce",
        )

    @staticmethod
    def normalize_text(
        series: pd.Series,
    ) -> pd.Series:
        return (
            series.astype("string")
            .str.strip()
            .str.casefold()
        )
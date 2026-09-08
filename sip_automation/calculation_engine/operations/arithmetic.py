from __future__ import annotations

from functools import reduce
from typing import Any

import pandas as pd

from sip_automation.calculation_engine.context import (
    CalculationContext,
)
from sip_automation.calculation_engine.operations.base import (
    BaseOperation,
    OperationExecutionError,
)


class AddOperation(BaseOperation):
    operation_name = "add"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = self.resolve_inputs(
            dataframe,
            definition.get("inputs", []),
            context,
        )

        if not inputs:
            raise OperationExecutionError(
                "add requires at least one input."
            )

        numeric_frame = pd.concat(
            [
                self.to_numeric(series)
                for series in inputs
            ],
            axis=1,
        )

        if definition.get("null_as_zero", False):
            return numeric_frame.fillna(0).sum(axis=1)

        return numeric_frame.sum(
            axis=1,
            min_count=len(inputs),
        )


class SubtractOperation(BaseOperation):
    operation_name = "subtract"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = self.resolve_inputs(
            dataframe,
            definition.get("inputs", []),
            context,
        )

        if len(inputs) != 2:
            raise OperationExecutionError(
                "subtract requires exactly two inputs."
            )

        left = self.to_numeric(inputs[0])
        right = self.to_numeric(inputs[1])

        return left - right


class MultiplyOperation(BaseOperation):
    operation_name = "multiply"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = self.resolve_inputs(
            dataframe,
            definition.get("inputs", []),
            context,
        )

        if not inputs:
            raise OperationExecutionError(
                "multiply requires at least one input."
            )

        numeric_inputs = [
            self.to_numeric(series)
            for series in inputs
        ]

        if definition.get("null_as_one", False):
            numeric_inputs = [
                series.fillna(1)
                for series in numeric_inputs
            ]

        return reduce(
            lambda left, right: left * right,
            numeric_inputs,
        )


class DivideOperation(BaseOperation):
    operation_name = "divide"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = definition.get("inputs", {})

        if not isinstance(inputs, dict):
            raise OperationExecutionError(
                "divide inputs must be a dictionary."
            )

        numerator_definition = inputs.get(
            "numerator"
        )
        denominator_definition = inputs.get(
            "denominator"
        )

        if (
            numerator_definition is None
            or denominator_definition is None
        ):
            raise OperationExecutionError(
                "divide requires numerator and denominator."
            )

        numerator = self.to_numeric(
            self.resolve_operand(
                dataframe,
                numerator_definition,
                context,
            )
        )

        denominator = self.to_numeric(
            self.resolve_operand(
                dataframe,
                denominator_definition,
                context,
            )
        )

        valid_denominator = denominator.where(
            denominator.ne(0)
        )

        result = numerator.div(valid_denominator)

        if "zero_result" in definition:
            zero_mask = denominator.eq(0)

            result = result.where(
                ~zero_mask,
                definition.get("zero_result"),
            )

        return result


class MinimumOperation(BaseOperation):
    operation_name = "minimum"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = self.resolve_inputs(
            dataframe,
            definition.get("inputs", []),
            context,
        )

        if not inputs:
            raise OperationExecutionError(
                "minimum requires at least one input."
            )

        numeric_frame = pd.concat(
            [
                self.to_numeric(series)
                for series in inputs
            ],
            axis=1,
        )

        return numeric_frame.min(
            axis=1,
            skipna=bool(
                definition.get("skip_nulls", True)
            ),
        )


class MaximumOperation(BaseOperation):
    operation_name = "maximum"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = self.resolve_inputs(
            dataframe,
            definition.get("inputs", []),
            context,
        )

        if not inputs:
            raise OperationExecutionError(
                "maximum requires at least one input."
            )

        numeric_frame = pd.concat(
            [
                self.to_numeric(series)
                for series in inputs
            ],
            axis=1,
        )

        return numeric_frame.max(
            axis=1,
            skipna=bool(
                definition.get("skip_nulls", True)
            ),
        )


class AbsoluteOperation(BaseOperation):
    operation_name = "absolute"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        input_definition = definition.get("input")

        if input_definition is None:
            raise OperationExecutionError(
                "absolute requires an input."
            )

        values = self.to_numeric(
            self.resolve_operand(
                dataframe,
                input_definition,
                context,
            )
        )

        return values.abs()
from __future__ import annotations

from typing import Any

import pandas as pd

from sip_automation.calculation_engine.context import (
    CalculationContext,
)
from sip_automation.calculation_engine.operations.base import (
    BaseOperation,
    OperationExecutionError,
)


class ConditionalSupport(BaseOperation):
    """
    Shared condition evaluation.
    """

    def _evaluate_condition(
        self,
        dataframe: pd.DataFrame,
        condition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        if "all" in condition:
            child_conditions = condition["all"]

            masks = [
                self._evaluate_condition(
                    dataframe,
                    child,
                    context,
                )
                for child in child_conditions
            ]

            result = pd.Series(
                True,
                index=dataframe.index,
            )

            for mask in masks:
                result &= mask.fillna(False)

            return result

        if "any" in condition:
            child_conditions = condition["any"]

            masks = [
                self._evaluate_condition(
                    dataframe,
                    child,
                    context,
                )
                for child in child_conditions
            ]

            result = pd.Series(
                False,
                index=dataframe.index,
            )

            for mask in masks:
                result |= mask.fillna(False)

            return result

        operator = str(
            condition.get("operator", "equals")
        ).strip().lower()

        left_definition = condition.get("left")

        if left_definition is None:
            raise OperationExecutionError(
                "Condition requires a left operand."
            )

        left = self.resolve_operand(
            dataframe,
            left_definition,
            context,
        )

        if operator == "is_null":
            return left.isna()

        if operator == "not_null":
            return left.notna()

        right_definition = condition.get("right")

        if operator in {"in", "not_in"}:
            values = self._resolve_collection(
                right_definition,
                context,
            )

            result = left.isin(values)

            if operator == "not_in":
                result = ~result

            return result

        if right_definition is None:
            raise OperationExecutionError(
                f"Condition operator {operator!r} "
                "requires a right operand."
            )

        right = self.resolve_operand(
            dataframe,
            right_definition,
            context,
        )

        if operator == "equals":
            result = left.eq(right)

        elif operator == "not_equals":
            result = left.ne(right)

        elif operator == "greater_than":
            result = left.gt(right)

        elif operator == "greater_than_or_equal":
            result = left.ge(right)

        elif operator == "less_than":
            result = left.lt(right)

        elif operator == "less_than_or_equal":
            result = left.le(right)

        else:
            raise OperationExecutionError(
                f"Unsupported condition operator: "
                f"{operator!r}."
            )

        return result.fillna(False)

    @staticmethod
    def _resolve_collection(
        definition: Any,
        context: CalculationContext,
    ) -> list[Any]:
        if isinstance(definition, dict):
            if "value" in definition:
                value = definition["value"]

            elif "parameter" in definition:
                value = context.get_parameter(
                    str(definition["parameter"]),
                    required=bool(
                        definition.get(
                            "required",
                            False,
                        )
                    ),
                )

            elif "static_reference" in definition:
                reference = definition["static_reference"]

                if isinstance(reference, dict):
                    reference = reference.get("path")

                if not reference:
                    raise OperationExecutionError(
                        "Collection static_reference must "
                        "contain a path."
                    )

                value = context.get_static_reference(
                    str(reference)
                )

            else:
                raise OperationExecutionError(
                    "Collection operand must define value, "
                    "parameter, or static_reference."
                )

        else:
            value = definition

        if isinstance(value, list):
            return value

        if isinstance(value, tuple):
            return list(value)

        return [value]


class IfElseOperation(ConditionalSupport):
    operation_name = "if_else"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        condition = definition.get("condition")

        if not isinstance(condition, dict):
            raise OperationExecutionError(
                "if_else requires a condition."
            )

        condition_mask = self._evaluate_condition(
            dataframe,
            condition,
            context,
        )

        true_values = self.resolve_operand(
            dataframe,
            definition.get(
                "then",
                {"value": None},
            ),
            context,
        )

        false_values = self.resolve_operand(
            dataframe,
            definition.get(
                "else",
                {"value": None},
            ),
            context,
        )

        return true_values.where(
            condition_mask,
            false_values,
        )


class CaseWhenOperation(ConditionalSupport):
    operation_name = "case_when"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        cases = definition.get("cases", [])

        if not isinstance(cases, list) or not cases:
            raise OperationExecutionError(
                "case_when requires at least one case."
            )

        result = self.resolve_operand(
            dataframe,
            definition.get(
                "default",
                {"value": None},
            ),
            context,
        )

        unassigned_mask = pd.Series(
            True,
            index=dataframe.index,
        )

        for case in cases:
            if not isinstance(case, dict):
                raise OperationExecutionError(
                    "Each case_when case must be "
                    "a dictionary."
                )

            condition = case.get("when")

            if not isinstance(condition, dict):
                raise OperationExecutionError(
                    "Each case_when case requires when."
                )

            case_mask = self._evaluate_condition(
                dataframe,
                condition,
                context,
            )

            applicable_mask = (
                case_mask.fillna(False)
                & unassigned_mask
            )

            case_values = self.resolve_operand(
                dataframe,
                case.get(
                    "then",
                    {"value": None},
                ),
                context,
            )

            result = result.where(
                ~applicable_mask,
                case_values,
            )

            unassigned_mask &= ~applicable_mask

        return result
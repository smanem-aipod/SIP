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


class CapOperation(BaseOperation):
    """
    Restrict a value to a configured maximum.
    """

    operation_name = "cap"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        value_definition = definition.get("input")
        cap_definition = definition.get("cap")

        if value_definition is None or cap_definition is None:
            raise OperationExecutionError(
                "cap requires input and cap."
            )

        values = self.to_numeric(
            self.resolve_operand(
                dataframe,
                value_definition,
                context,
            )
        )

        caps = self.to_numeric(
            self.resolve_operand(
                dataframe,
                cap_definition,
                context,
            )
        )

        return pd.concat(
            [values, caps],
            axis=1,
        ).min(axis=1)


class FloorOperation(BaseOperation):
    """
    Restrict a value to a configured minimum.
    """

    operation_name = "floor"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        value_definition = definition.get("input")
        floor_definition = definition.get("floor")

        if (
            value_definition is None
            or floor_definition is None
        ):
            raise OperationExecutionError(
                "floor requires input and floor."
            )

        values = self.to_numeric(
            self.resolve_operand(
                dataframe,
                value_definition,
                context,
            )
        )

        floors = self.to_numeric(
            self.resolve_operand(
                dataframe,
                floor_definition,
                context,
            )
        )

        return pd.concat(
            [values, floors],
            axis=1,
        ).max(axis=1)


class ClampOperation(BaseOperation):
    """
    Restrict a value between a minimum and maximum.
    """

    operation_name = "clamp"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        input_definition = definition.get("input")
        minimum_definition = definition.get("minimum")
        maximum_definition = definition.get("maximum")

        if input_definition is None:
            raise OperationExecutionError(
                "clamp requires input."
            )

        values = self.to_numeric(
            self.resolve_operand(
                dataframe,
                input_definition,
                context,
            )
        )

        result = values.copy()

        if minimum_definition is not None:
            minimum_values = self.to_numeric(
                self.resolve_operand(
                    dataframe,
                    minimum_definition,
                    context,
                )
            )

            result = pd.concat(
                [result, minimum_values],
                axis=1,
            ).max(axis=1)

        if maximum_definition is not None:
            maximum_values = self.to_numeric(
                self.resolve_operand(
                    dataframe,
                    maximum_definition,
                    context,
                )
            )

            result = pd.concat(
                [result, maximum_values],
                axis=1,
            ).min(axis=1)

        return result


class ProrateOperation(BaseOperation):
    """
    Prorate an amount using an eligible-period fraction.

    Formula:

        amount × eligible_units / total_units
    """

    operation_name = "prorate"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = definition.get("inputs", {})

        if not isinstance(inputs, dict):
            raise OperationExecutionError(
                "prorate inputs must be a dictionary."
            )

        amount_definition = inputs.get("amount")
        eligible_definition = inputs.get(
            "eligible_units"
        )
        total_definition = inputs.get(
            "total_units"
        )

        if (
            amount_definition is None
            or eligible_definition is None
            or total_definition is None
        ):
            raise OperationExecutionError(
                "prorate requires amount, eligible_units, "
                "and total_units."
            )

        amount = self.to_numeric(
            self.resolve_operand(
                dataframe,
                amount_definition,
                context,
            )
        )

        eligible_units = self.to_numeric(
            self.resolve_operand(
                dataframe,
                eligible_definition,
                context,
            )
        )

        total_units = self.to_numeric(
            self.resolve_operand(
                dataframe,
                total_definition,
                context,
            )
        )

        valid_total = total_units.where(
            total_units.ne(0)
        )

        factor = eligible_units.div(valid_total)

        if definition.get("limit_factor", True):
            factor = factor.clip(
                lower=0,
                upper=1,
            )

        return amount * factor


class RoundOperation(BaseOperation):
    operation_name = "round"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        input_definition = definition.get("input")

        if input_definition is None:
            raise OperationExecutionError(
                "round requires input."
            )

        decimals = int(
            definition.get("decimals", 2)
        )

        values = self.to_numeric(
            self.resolve_operand(
                dataframe,
                input_definition,
                context,
            )
        )

        return values.round(decimals)

class OverpaymentOperation(BaseOperation):
    operation_name = "overpayment"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = definition.get("inputs", {})

        if not isinstance(inputs, dict):
            raise OperationExecutionError(
                "overpayment inputs must be a dictionary."
            )

        required_inputs = {
            "ytd_sip_earned",
            "q1_payment_region_currency",
            "q2_payment_region_currency",
            "q3_payment_region_currency",
            "guarantee_sip_q2",
            "crossed_gtee_payment_region_currency",
        }

        missing_inputs = sorted(
            required_inputs - set(inputs)
        )

        if missing_inputs:
            raise OperationExecutionError(
                f"overpayment is missing inputs: "
                f"{missing_inputs}."
            )

        ytd_sip_earned = self.to_numeric(
            self.resolve_operand(
                dataframe,
                inputs["ytd_sip_earned"],
                context,
            )
        ).fillna(0)

        q1_payment = self.to_numeric(
            self.resolve_operand(
                dataframe,
                inputs["q1_payment_region_currency"],
                context,
            )
        ).fillna(0)

        q2_payment = self.to_numeric(
            self.resolve_operand(
                dataframe,
                inputs["q2_payment_region_currency"],
                context,
            )
        ).fillna(0)

        q3_payment = self.to_numeric(
            self.resolve_operand(
                dataframe,
                inputs["q3_payment_region_currency"],
                context,
            )
        ).fillna(0)

        guarantee_sip_q2 = self.to_numeric(
            self.resolve_operand(
                dataframe,
                inputs["guarantee_sip_q2"],
                context,
            )
        ).fillna(0)

        crossed_gtee_payment = self.to_numeric(
            self.resolve_operand(
                dataframe,
                inputs[
                    "crossed_gtee_payment_region_currency"
                ],
                context,
            )
        ).fillna(0)

        calculated_overpayment = (
            ytd_sip_earned
            - q1_payment
            - q2_payment
            - q3_payment
            + guarantee_sip_q2
            + crossed_gtee_payment
        )

        condition = (
            ytd_sip_earned.gt(0)
            & q1_payment.gt(ytd_sip_earned)
        )

        result = pd.Series(
            0.0,
            index=dataframe.index,
        )

        result.loc[condition] = (
            calculated_overpayment.loc[condition]
        )

        return result


class NacsRegionCurrencyOperation(BaseOperation):
    operation_name = "nacs_region_currency"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        inputs = definition.get("inputs", {})

        if not isinstance(inputs, dict):
            raise OperationExecutionError(
                "nacs_region_currency inputs must be "
                "a dictionary."
            )

        required_inputs = {
            "ytd_sip_earned",
            "crossed_gtee_payment_region_currency",
            "overpayment",
            "q1_payment_region_currency",
            "q2_payment_region_currency",
            "q3_payment_region_currency",
            "guarantee_sip_q2",
            "guarantee_eligibility_fy26_months",
        }

        missing_inputs = sorted(
            required_inputs - set(inputs)
        )

        if missing_inputs:
            raise OperationExecutionError(
                f"nacs_region_currency is missing inputs: "
                f"{missing_inputs}."
            )

        def resolve_numeric(input_name: str) -> pd.Series:
            return self.to_numeric(
                self.resolve_operand(
                    dataframe,
                    inputs[input_name],
                    context,
                )
            ).fillna(0)

        ytd_sip_earned = resolve_numeric(
            "ytd_sip_earned"
        )

        crossed_gtee_payment = resolve_numeric(
            "crossed_gtee_payment_region_currency"
        )

        overpayment = resolve_numeric(
            "overpayment"
        )

        q1_payment = resolve_numeric(
            "q1_payment_region_currency"
        )

        q2_payment = resolve_numeric(
            "q2_payment_region_currency"
        )

        q3_payment = resolve_numeric(
            "q3_payment_region_currency"
        )

        guarantee_sip_q2 = resolve_numeric(
            "guarantee_sip_q2"
        )

        eligibility_months = resolve_numeric(
            "guarantee_eligibility_fy26_months"
        )

        payment_deductions = (
            overpayment
            + q1_payment
            + q2_payment
            + q3_payment
        )

        negativity_check = (
            ytd_sip_earned
            + crossed_gtee_payment
            - payment_deductions
        )

        earned_after_deductions = (
            ytd_sip_earned
            - payment_deductions
        ).where(
            negativity_check.ge(0),
            0,
        )

        partial_guarantee_addition = (
            ytd_sip_earned.where(
                eligibility_months.gt(0)
                & eligibility_months.lt(3),
                0,
            )
        )

        calculated_value = (
            earned_after_deductions
            + guarantee_sip_q2
            + crossed_gtee_payment
            + partial_guarantee_addition
        )

        return calculated_value.where(
            ytd_sip_earned.ge(
                crossed_gtee_payment
            ),
            0,
        )    

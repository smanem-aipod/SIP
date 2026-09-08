from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from sip_automation.calculation_engine.context import (
    CalculationContext,
)
from sip_automation.calculation_engine.operations.base import (
    BaseOperation,
    OperationExecutionError,
)


class MonthsEligibleOperation(BaseOperation):
    """
    Calculate annual SIP-eligible months for the selected
    fiscal year and quarter.

    Fiscal year convention:
        FY26 = 01-Oct-2025 through 30-Sep-2026

    Quarter eligibility cutoffs:
        Q1 = 05-Dec-2025
        Q2 = 05-Mar-2026
        Q3 = 05-Jun-2026
        Q4 = 05-Sep-2026

    Rules:
        1. Eligible after the annual cutoff -> 0
        2. Eligible on/before the previous FY end -> 12
        3. Eligible after the selected-quarter cutoff -> 0
        4. Otherwise use fiscal months remaining.
        5. If eligibility day is after the 5th,
           subtract one month.
    """

    operation_name = "months_eligible"

    _FISCAL_MONTH_VALUES: dict[int, int] = {
        10: 12,
        11: 11,
        12: 10,
        1: 9,
        2: 8,
        3: 7,
        4: 6,
        5: 5,
        6: 4,
        7: 3,
        8: 2,
        9: 1,
    }

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        input_definition = definition.get(
            "input",
            {
                "column": "sip_eligible_date",
            },
        )

        eligible_dates = self.resolve_operand(
            dataframe,
            input_definition,
            context,
        )

        eligible_dates = pd.to_datetime(
            eligible_dates,
            errors="coerce",
        )

        quarter = str(
            context.get_parameter(
                "quarter",
                required=True,
            )
        ).strip().upper()

        fiscal_year = context.get_parameter(
            "fiscal_year",
            required=True,
        )

        try:
            fiscal_year = int(fiscal_year)
        except (TypeError, ValueError) as exc:
            raise OperationExecutionError(
                "months_eligible requires fiscal_year "
                "to be an integer such as 2026."
            ) from exc

        if quarter not in {
            "Q1",
            "Q2",
            "Q3",
            "Q4",
        }:
            raise OperationExecutionError(
                "months_eligible requires quarter to be "
                "Q1, Q2, Q3, or Q4."
            )

        previous_calendar_year = fiscal_year - 1

        previous_fy_end = pd.Timestamp(
            date(
                previous_calendar_year,
                9,
                30,
            )
        )

        annual_cutoff = pd.Timestamp(
            date(
                fiscal_year,
                9,
                5,
            )
        )

        quarter_cutoffs = {
            "Q1": pd.Timestamp(
                date(
                    previous_calendar_year,
                    12,
                    5,
                )
            ),
            "Q2": pd.Timestamp(
                date(
                    fiscal_year,
                    3,
                    5,
                )
            ),
            "Q3": pd.Timestamp(
                date(
                    fiscal_year,
                    6,
                    5,
                )
            ),
            "Q4": pd.Timestamp(
                date(
                    fiscal_year,
                    9,
                    5,
                )
            ),
        }

        quarter_cutoff = quarter_cutoffs[quarter]

        null_result = definition.get(
            "null_result",
            0,
        )

        result = pd.Series(
            null_result,
            index=dataframe.index,
            dtype="Int64",
        )

        valid_date_mask = eligible_dates.notna()

        after_annual_cutoff = (
            valid_date_mask
            & eligible_dates.gt(annual_cutoff)
        )

        full_year_eligible = (
            valid_date_mask
            & eligible_dates.le(previous_fy_end)
        )

        after_quarter_cutoff = (
            valid_date_mask
            & ~after_annual_cutoff
            & ~full_year_eligible
            & eligible_dates.gt(quarter_cutoff)
        )

        calculated_mask = (
            valid_date_mask
            & ~after_annual_cutoff
            & ~full_year_eligible
            & ~after_quarter_cutoff
        )

        result.loc[after_annual_cutoff] = 0
        result.loc[full_year_eligible] = 12
        result.loc[after_quarter_cutoff] = 0

        if calculated_mask.any():
            month_values = (
                eligible_dates.loc[
                    calculated_mask
                ]
                .dt.month
                .map(self._FISCAL_MONTH_VALUES)
                .astype("Int64")
            )

            after_fifth_adjustment = (
                eligible_dates.loc[
                    calculated_mask
                ]
                .dt.day
                .gt(5)
                .astype("Int64")
            )

            calculated_values = (
                month_values
                - after_fifth_adjustment
            ).clip(
                lower=0,
                upper=12,
            )

            result.loc[calculated_mask] = (
                calculated_values
            )

        return result.astype("Int64")
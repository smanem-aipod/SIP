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


class ConstantOperation(BaseOperation):
    operation_name = "constant"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        if "value" in definition:
            value = definition["value"]

        elif "static_reference" in definition:
            reference = definition["static_reference"]

            if isinstance(reference, dict):
                reference = reference.get("path")

            if not reference:
                raise OperationExecutionError(
                    "constant static_reference must contain a path."
                )

            value = context.get_static_reference(
                str(reference)
            )

        else:
            raise OperationExecutionError(
                "constant requires value or static_reference."
            )

        return pd.Series(
            value,
            index=dataframe.index,
        )
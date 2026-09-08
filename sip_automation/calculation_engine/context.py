from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

import pandas as pd


@dataclass(frozen=True)
class CalculationContext:
    """
    Input datasets, runtime parameters, and static reference data
    required by a SIP calculation run.
    """

    employee: pd.DataFrame
    bp: pd.DataFrame
    sales: pd.DataFrame
    nacs_guarantee: pd.DataFrame
    ytd_payments: pd.DataFrame
    bdm: pd.DataFrame
    fx_rates: pd.DataFrame | None = None

    employee_seller_bridge: pd.DataFrame | None = None
    precompute_exceptions: pd.DataFrame | None = None
    cam_allocation_overrides: pd.DataFrame | None = None

    pipeline_run_id: UUID | None = None
    fiscal_year: int | None = None
    quarter: str | None = None

    parameters: dict[str, Any] | None = None
    static_reference_data: dict[str, Any] | None = None

    def get_dataset(
        self,
        dataset_name: str,
    ) -> pd.DataFrame:
        datasets = {
            "employee": self.employee,
            "bp": self.bp,
            "sales": self.sales,
            "nacs_guarantee": self.nacs_guarantee,
            "ytd_payments": self.ytd_payments,
            "bdm": self.bdm,
            "fx_rates": self.fx_rates,
            "employee_seller_bridge": (
                self.employee_seller_bridge
            ),
            "precompute_exceptions": (
                self.precompute_exceptions
            ),
        }

        if dataset_name not in datasets:
            raise KeyError(
                f"Unknown calculation dataset: "
                f"{dataset_name!r}."
            )

        dataset = datasets[dataset_name]

        if dataset is None:
            raise ValueError(
                f"Calculation dataset "
                f"{dataset_name!r} is unavailable."
            )

        return dataset

    def get_parameter(
        self,
        parameter_name: str,
        *,
        default: Any = None,
        required: bool = False,
    ) -> Any:
        built_in_parameters = {
            "pipeline_run_id": self.pipeline_run_id,
            "fiscal_year": self.fiscal_year,
            "quarter": self.quarter,
        }

        if parameter_name in built_in_parameters:
            value = built_in_parameters[
                parameter_name
            ]

        else:
            value = (self.parameters or {}).get(
                parameter_name,
                default,
            )

        if required and value is None:
            raise ValueError(
                f"Required calculation parameter is "
                f"unavailable: {parameter_name!r}."
            )

        return value

    def get_static_reference(
        self,
        reference_path: str,
        *,
        default: Any = None,
        required: bool = True,
    ) -> Any:
        """
        Resolve a dotted path from static_reference_data.

        Example:

            constants.low_margin_threshold

        resolves:

            static_reference_data[
                "constants"
            ][
                "low_margin_threshold"
            ]
        """

        if not reference_path:
            raise ValueError(
                "Static reference path cannot be empty."
            )

        current: Any = (
            self.static_reference_data or {}
        )

        for part in reference_path.split("."):
            if not isinstance(current, dict):
                if required:
                    raise KeyError(
                        f"Static reference path "
                        f"{reference_path!r} is invalid at "
                        f"{part!r}."
                    )

                return default

            if part not in current:
                if required:
                    raise KeyError(
                        f"Static reference is unavailable: "
                        f"{reference_path!r}."
                    )

                return default

            current = current[part]

        if current is None and required:
            raise ValueError(
                f"Static reference "
                f"{reference_path!r} resolved to None."
            )

        return current
from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from sip_automation.core.exceptions import TransformationError
from sip_automation.core.logging import get_logger
from sip_automation.core.run_context import RunContext


logger = get_logger(__name__)


TransformationOperation = Callable[
    [pd.DataFrame, dict[str, Any], RunContext],
    pd.DataFrame,
]


class TransformationEngine:
    """
    Execute controlled, registered derived-column operations.
    """

    def __init__(self) -> None:
        self._operations: dict[
            str,
            TransformationOperation,
        ] = {
            "sum": self._sum,
            "multiply": self._multiply,
            "safe_divide": self._safe_divide,
            "concat": self._concat,
            "coalesce": self._coalesce,
            "constant": self._constant,
            "runtime_parameter": (
                self._runtime_parameter
            ),
            "runtime_date": self._runtime_date,
            "subtract": self._subtract,
            "employee_sip_eligible_date": (
                self._employee_sip_eligible_date
            ),
            "supply_point_sa_classification": (
                self._supply_point_sa_classification
            ),
            "operational_sbu_classification": (
                self._operational_sbu_classification
            ),
            "grouped_margin_enrichment": (
                self._grouped_margin_enrichment
            ),
            "gp_flag_classification": (
                self._gp_flag_classification
            ),
            "gp_flag_cam_classification": (
                self._gp_flag_cam_classification
            ),
            "add": self._sum,
            "subtract_many": self._subtract_many,
            "minimum": self._minimum,
            "copy": self._copy,
            "add_days": self._add_days,
            "prorate": self._prorate,
            "nacs_fy25_eligibility_months": (
                self._nacs_fy25_eligibility_months
            ),
            "nacs_fy26_eligibility_months": (
                self._nacs_fy26_eligibility_months
            ),
            "nacs_quarter_eligibility_months": (
                self._nacs_quarter_eligibility_months
            ),
            "nacs_guarantee_status": (
                self._nacs_guarantee_status
            ),

        }

    def apply_stage(
        self,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        derived_columns: dict[str, Any] | None,
        stage: str,
        context: RunContext,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        for output_column, definition in (
            derived_columns or {}
        ).items():
            if not isinstance(definition, dict):
                raise TransformationError(
                    f"Derived column {output_column!r} in "
                    f"{logical_table_name!r} must be an object."
                )

            if not definition.get("enabled", True):
                continue

            configured_stage = definition.get(
                "stage",
                "before_enrichment",
            )

            if configured_stage != stage:
                continue

            operation_name = definition.get(
                "operation"
            )

            operation = self._operations.get(
                str(operation_name)
            )

            if operation is None:
                raise TransformationError(
                    f"Unsupported transformation operation "
                    f"{operation_name!r} for column "
                    f"{output_column!r}."
                )

            operation_definition = {
                **definition,
                "output": output_column,
            }

            try:
                result = operation(
                    result,
                    operation_definition,
                    context,
                )

            except Exception as exc:
                if isinstance(exc, TransformationError):
                    raise

                raise TransformationError(
                    f"Transformation {operation_name!r} failed "
                    f"for {logical_table_name!r}."
                    f"{output_column!r}."
                ) from exc

        logger.info(
            "transformation_stage_completed",
            logical_table_name=logical_table_name,
            stage=stage,
            row_count=len(result),
            column_count=len(result.columns),
        )

        return result

    def register(
        self,
        operation_name: str,
        operation: TransformationOperation,
        *,
        replace: bool = False,
    ) -> None:
        normalized_name = (
            operation_name.strip().lower()
        )

        if (
            normalized_name in self._operations
            and not replace
        ):
            raise TransformationError(
                f"Transformation operation is already "
                f"registered: {normalized_name!r}"
            )

        self._operations[normalized_name] = operation

    @staticmethod
    def _require_columns(
        dataframe: pd.DataFrame,
        columns: list[str],
    ) -> None:
        missing = sorted(
            set(columns) - set(dataframe.columns)
        )

        if missing:
            raise TransformationError(
                f"Transformation requires missing columns: "
                f"{missing}"
            )

    def _sum(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        inputs = definition.get("inputs", [])
        output = definition["output"]

        self._require_columns(dataframe, inputs)

        numeric = dataframe[inputs].apply(
            pd.to_numeric,
            errors="coerce",
        )

        if definition.get("null_as_zero", False):
            result_values = numeric.fillna(0).sum(
                axis=1
            )
        else:
            result_values = numeric.sum(
                axis=1,
                min_count=len(inputs),
            )

        result = dataframe.copy()
        result[output] = result_values

        return result

    def _multiply(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        inputs = definition.get("inputs", [])

        if isinstance(inputs, dict):
            inputs = list(inputs.values())

        if len(inputs) != 2:
            raise TransformationError(
                "multiply requires exactly two inputs."
            )

        self._require_columns(dataframe, inputs)

        result = dataframe.copy()

        left = pd.to_numeric(
            result[inputs[0]],
            errors="coerce",
        )

        right = pd.to_numeric(
            result[inputs[1]],
            errors="coerce",
        )

        result[definition["output"]] = left * right

        return result

    def _safe_divide(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        inputs = definition.get("inputs", {})

        numerator_column = inputs.get("numerator")
        denominator_column = inputs.get("denominator")

        if not numerator_column or not denominator_column:
            raise TransformationError(
                "safe_divide requires numerator and denominator."
            )

        self._require_columns(
            dataframe,
            [
                numerator_column,
                denominator_column,
            ],
        )

        numerator = pd.to_numeric(
            dataframe[numerator_column],
            errors="coerce",
        )

        denominator = pd.to_numeric(
            dataframe[denominator_column],
            errors="coerce",
        )

        result_values = numerator.div(
            denominator.where(denominator.ne(0))
        )

        result = dataframe.copy()
        result[definition["output"]] = result_values

        return result

    def _subtract(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        inputs = definition.get("inputs", [])

        if len(inputs) != 2:
            raise TransformationError(
                "subtract requires exactly two inputs."
            )

        self._require_columns(dataframe, inputs)

        result = dataframe.copy()

        left = pd.to_numeric(
            result[inputs[0]],
            errors="coerce",
        )

        right = pd.to_numeric(
            result[inputs[1]],
            errors="coerce",
        )

        result[definition["output"]] = left - right

        return result

    def _subtract_many(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        starting_definition = inputs.get(
            "starting_value"
        )

        subtract_columns = inputs.get(
            "subtract",
            [],
        )

        if starting_definition is None:
            raise TransformationError(
                "subtract_many requires starting_value."
            )

        if not isinstance(subtract_columns, list):
            raise TransformationError(
                "subtract_many subtract must be a list."
            )

        self._require_columns(
            dataframe,
            subtract_columns,
        )

        if isinstance(starting_definition, dict):
            parameter_name = starting_definition.get(
                "parameter"
            )

            if not parameter_name:
                raise TransformationError(
                    "subtract_many starting_value parameter "
                    "is invalid."
                )

            starting_value = context.get_parameter(
                str(parameter_name),
                required=True,
            )

            result_values = pd.Series(
                starting_value,
                index=dataframe.index,
                dtype="float64",
            )

        else:
            self._require_columns(
                dataframe,
                [str(starting_definition)],
            )

            result_values = pd.to_numeric(
                dataframe[str(starting_definition)],
                errors="coerce",
            )

        for column_name in subtract_columns:
            result_values = result_values - pd.to_numeric(
                dataframe[column_name],
                errors="coerce",
            ).fillna(0)

        result = dataframe.copy()
        result[definition["output"]] = result_values

        return result


    def _minimum(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        value_column = inputs.get("value")
        maximum_definition = inputs.get("maximum")

        if not value_column:
            raise TransformationError(
                "minimum requires inputs.value."
            )

        self._require_columns(
            dataframe,
            [value_column],
        )

        if isinstance(maximum_definition, dict):
            parameter_name = maximum_definition.get(
                "parameter"
            )

            maximum = context.get_parameter(
                str(parameter_name),
                required=True,
            )
        else:
            maximum = maximum_definition

        if maximum is None:
            raise TransformationError(
                "minimum requires a maximum value."
            )

        values = pd.to_numeric(
            dataframe[value_column],
            errors="coerce",
        )

        result = dataframe.copy()
        result[definition["output"]] = values.clip(
            upper=float(maximum)
        )

        return result


    def _copy(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        input_column = definition.get("input")

        if not input_column:
            raise TransformationError(
                "copy requires input."
            )

        self._require_columns(
            dataframe,
            [input_column],
        )

        result = dataframe.copy()
        result[definition["output"]] = result[
            input_column
        ]

        return result


    def _add_days(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        date_column = inputs.get("date")
        days_definition = inputs.get("days")

        if not date_column:
            raise TransformationError(
                "add_days requires inputs.date."
            )

        self._require_columns(
            dataframe,
            [date_column],
        )

        if isinstance(days_definition, dict):
            parameter_name = days_definition.get(
                "parameter"
            )

            days = context.get_parameter(
                str(parameter_name),
                required=True,
            )
        else:
            days = days_definition

        if days is None:
            raise TransformationError(
                "add_days requires a days value."
            )

        dates = pd.to_datetime(
            dataframe[date_column],
            errors="coerce",
        )

        result = dataframe.copy()
        result[definition["output"]] = (
            dates + pd.to_timedelta(
                int(days),
                unit="D",
            )
        ).dt.date

        return result


    def _prorate(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        amount_column = inputs.get("amount")
        eligible_units_column = inputs.get(
            "eligible_units"
        )
        total_units_definition = inputs.get(
            "total_units"
        )

        if not amount_column or not eligible_units_column:
            raise TransformationError(
                "prorate requires amount and eligible_units."
            )

        self._require_columns(
            dataframe,
            [
                amount_column,
                eligible_units_column,
            ],
        )

        if isinstance(total_units_definition, dict):
            parameter_name = total_units_definition.get(
                "parameter"
            )

            total_units = context.get_parameter(
                str(parameter_name),
                required=True,
            )
        else:
            total_units = total_units_definition

        if total_units is None:
            raise TransformationError(
                "prorate requires total_units."
            )

        total_units = float(total_units)

        if total_units == 0:
            raise TransformationError(
                "prorate total_units cannot be zero."
            )

        amount = pd.to_numeric(
            dataframe[amount_column],
            errors="coerce",
        )

        eligible_units = pd.to_numeric(
            dataframe[eligible_units_column],
            errors="coerce",
        )

        result = dataframe.copy()
        result[definition["output"]] = (
            amount * eligible_units / total_units
        )

        return result

    def _concat(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        inputs = definition.get("inputs", [])
        separator = str(
            definition.get("separator", "")
        )

        self._require_columns(dataframe, inputs)

        result = dataframe.copy()

        values = (
            result[inputs]
            .fillna("")
            .astype(str)
        )

        result[definition["output"]] = values.agg(
            separator.join,
            axis=1,
        )

        return result

    def _coalesce(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        inputs = definition.get("inputs", [])

        self._require_columns(dataframe, inputs)

        result = dataframe.copy()

        result[definition["output"]] = (
            result[inputs]
            .bfill(axis=1)
            .iloc[:, 0]
        )

        return result

    def _constant(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        del context

        result = dataframe.copy()
        result[definition["output"]] = definition.get(
            "value"
        )

        return result

    def _runtime_parameter(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        parameter = definition.get("parameter")

        if not parameter:
            raise TransformationError(
                "runtime_parameter requires parameter."
            )

        result = dataframe.copy()
        result[definition["output"]] = (
            context.get_parameter(
                str(parameter),
                required=True,
            )
        )

        return result

    def _runtime_date(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        parameter = definition.get(
            "parameter",
            "effective_start_date",
        )

        value = context.get_parameter(parameter)

        if value is None:
            value = context.started_at.date()

        elif isinstance(value, str):
            value = date.fromisoformat(value)

        result = dataframe.copy()
        result[definition["output"]] = value
        return result
    
    def _employee_sip_eligible_date(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Calculate SIP eligible date using the configured employee date rule.

        Rule:
        - If active_flag is Yes:
            termination_date, if present
            otherwise movement_date, if present
            otherwise hire_date
        - Otherwise:
            NULL
        """

        del context

        inputs = definition.get("inputs", {})

        active_flag_column = inputs.get("active_flag")
        termination_date_column = inputs.get(
            "termination_date"
        )
        movement_date_column = inputs.get(
            "movement_date"
        )
        hire_date_column = inputs.get("hire_date")

        required_columns = [
            active_flag_column,
            termination_date_column,
            movement_date_column,
            hire_date_column,
        ]

        if any(
            column is None
            for column in required_columns
        ):
            raise TransformationError(
                "employee_sip_eligible_date requires "
                "active_flag, termination_date, "
                "movement_date, and hire_date."
            )

        self._require_columns(
            dataframe,
            required_columns,
        )

        active_value = str(
            definition.get(
                "active_value",
                "Yes",
            )
        ).strip().casefold()

        result = dataframe.copy()

        active_mask = (
            result[active_flag_column]
            .astype("string")
            .str.strip()
            .str.casefold()
            .eq(active_value)
        )

        preferred_date = (
            result[
                [
                    termination_date_column,
                    movement_date_column,
                    hire_date_column,
                ]
            ]
            .bfill(axis=1)
            .iloc[:, 0]
        )

        result[definition["output"]] = (
            preferred_date.where(
                active_mask,
                None,
            )
        )

        return result  

    def _supply_point_sa_classification(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Classify a row based on supply point availability.

        Rule:
        - supply_point_name is null or contains configured null marker:
        "Non SA"
        - otherwise:
        "SA Materials"
        """

        del context

        inputs = definition.get("inputs", {})
        supply_point_column = inputs.get(
            "supply_point_name"
        )

        if not supply_point_column:
            raise TransformationError(
                "supply_point_sa_classification requires "
                "a supply_point_name input."
            )

        self._require_columns(
            dataframe,
            [supply_point_column],
        )

        configured_null_value = str(
            definition.get("null_value", "Null")
        ).strip().casefold()

        null_result = definition.get(
            "null_result",
            "Non SA",
        )

        non_null_result = definition.get(
            "non_null_result",
            "SA Materials",
        )

        result = dataframe.copy()

        values = result[supply_point_column]

        null_mask = (
            values.isna()
            | values.astype("string")
            .str.strip()
            .str.casefold()
            .eq(configured_null_value)
        )

        result[definition["output"]] = (
            null_mask.map(
                {
                    True: null_result,
                    False: non_null_result,
                }
            )
        )

        return result 

    def _operational_sbu_classification(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Classify every sales row as Operational or
        Non-Operational based on profit-centre SBU description.

        Matching is case-insensitive and whitespace-insensitive.
        Null values can optionally be treated as non-operational.
        """

        del context

        inputs = definition.get("inputs", {})
        source_column = inputs.get("column")

        if not source_column:
            raise TransformationError(
                "operational_sbu_classification requires "
                "inputs.column."
            )

        self._require_columns(
            dataframe,
            [source_column],
        )

        configured_values = definition.get(
            "non_operational_values",
            definition.get("values", []),
        )

        if not isinstance(configured_values, list):
            raise TransformationError(
                "operational_sbu_classification "
                "non_operational_values must be a list."
            )

        normalized_configured_values = {
            str(value).strip().casefold()
            for value in configured_values
            if value is not None
        }

        non_operational_result = definition.get(
            "non_operational_result",
            definition.get(
                "match_result",
                "Non-Operational SBU",
            ),
        )

        operational_result = definition.get(
            "operational_result",
            definition.get(
                "default_result",
                "Operational SBU",
            ),
        )

        null_is_non_operational = bool(
            definition.get(
                "null_is_non_operational",
                True,
            )
        )

        result = dataframe.copy()

        raw_values = result[source_column]

        normalized_values = (
            raw_values.astype("string")
            .str.strip()
            .str.casefold()
        )

        non_operational_mask = (
            normalized_values.isin(
                normalized_configured_values
            )
        )

        if null_is_non_operational:
            non_operational_mask = (
                non_operational_mask
                | raw_values.isna()
                | normalized_values.eq("")
            )

        result[definition["output"]] = np.where(
            non_operational_mask,
            non_operational_result,
            operational_result,
        )

        return result

    def _grouped_margin_enrichment(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Aggregate revenue and GP by configured business keys,
        classify grouped margin, and merge results back onto
        qualifying source rows.

        Optional:
            require_non_null:
                Only rows where all configured columns are non-null
                participate in the grouped calculation.

                Rows outside that population retain NULL values for
                the generated grouped columns.

        Classification:
            - revenue == 0 and GP == 0 -> N/A
            - revenue == 0 and GP != 0 -> OK
            - otherwise GP / revenue < threshold -> Below threshold
            - otherwise -> OK
        """

        del context

        group_by = definition.get("group_by", [])
        inputs = definition.get("inputs", {})
        outputs = definition.get("outputs", {})

        require_non_null = definition.get(
            "require_non_null",
            [],
        )

        revenue_column = inputs.get("revenue")
        gp_column = inputs.get("gp")

        if not isinstance(group_by, list) or not group_by:
            raise TransformationError(
                "grouped_margin_enrichment requires "
                "a non-empty group_by list."
            )

        if not isinstance(require_non_null, list):
            raise TransformationError(
                "grouped_margin_enrichment "
                "require_non_null must be a list."
            )

        if not revenue_column or not gp_column:
            raise TransformationError(
                "grouped_margin_enrichment requires "
                "inputs.revenue and inputs.gp."
            )

        required_output_keys = {
            "grouped_revenue",
            "grouped_gp",
            "classification",
        }

        missing_output_keys = (
            required_output_keys - set(outputs)
        )

        if missing_output_keys:
            raise TransformationError(
                "grouped_margin_enrichment is missing "
                f"output mappings: "
                f"{sorted(missing_output_keys)}."
            )

        required_columns = list(
            dict.fromkeys(
                group_by
                + require_non_null
                + [
                    revenue_column,
                    gp_column,
                ]
            )
        )

        self._require_columns(
            dataframe,
            required_columns,
        )

        grouped_revenue_column = str(
            outputs["grouped_revenue"]
        )

        grouped_gp_column = str(
            outputs["grouped_gp"]
        )

        classification_column = str(
            outputs["classification"]
        )

        threshold = float(
            definition.get(
                "threshold",
                0.15,
            )
        )

        zero_tolerance = float(
            definition.get(
                "zero_tolerance",
                0.000001,
            )
        )

        both_zero_result = definition.get(
            "both_zero_result",
            "N/A",
        )

        revenue_zero_gp_present_result = definition.get(
            "revenue_zero_gp_present_result",
            "OK",
        )

        below_threshold_result = definition.get(
            "below_threshold_result",
            "Below 15%",
        )

        pass_result = definition.get(
            "pass_result",
            "OK",
        )

        # -----------------------------------------------------
        # Determine which rows participate
        # -----------------------------------------------------

        eligible_mask = pd.Series(
            True,
            index=dataframe.index,
            dtype="bool",
        )

        for column_name in require_non_null:
            values = dataframe[column_name]

            non_null_mask = values.notna()

            if (
                pd.api.types.is_string_dtype(values)
                or values.dtype == object
            ):
                non_null_mask = (
                    non_null_mask
                    & values.astype("string")
                    .str.strip()
                    .ne("")
                )

            eligible_mask &= non_null_mask

        # Only qualifying rows participate in grouping.
        working = dataframe.loc[
            eligible_mask,
            group_by
            + [
                revenue_column,
                gp_column,
            ],
        ].copy()

        result = dataframe.copy()

        # Ensure output columns exist for every row.
        result[grouped_revenue_column] = np.nan
        result[grouped_gp_column] = np.nan
        result[classification_column] = None

        # Nothing eligible: return all-null CAM columns.
        if working.empty:
            return result

        working["__margin_revenue"] = pd.to_numeric(
            working[revenue_column],
            errors="coerce",
        ).fillna(0.0)

        working["__margin_gp"] = pd.to_numeric(
            working[gp_column],
            errors="coerce",
        ).fillna(0.0)

        grouped = (
            working.groupby(
                group_by,
                dropna=False,
                as_index=False,
            )
            .agg(
                **{
                    grouped_revenue_column: (
                        "__margin_revenue",
                        "sum",
                    ),
                    grouped_gp_column: (
                        "__margin_gp",
                        "sum",
                    ),
                }
            )
        )

        grouped_revenue = pd.to_numeric(
            grouped[grouped_revenue_column],
            errors="coerce",
        ).fillna(0.0)

        grouped_gp = pd.to_numeric(
            grouped[grouped_gp_column],
            errors="coerce",
        ).fillna(0.0)

        revenue_is_zero = (
            grouped_revenue.abs()
            .le(zero_tolerance)
        )

        gp_is_zero = (
            grouped_gp.abs()
            .le(zero_tolerance)
        )

        both_zero_mask = (
            revenue_is_zero
            & gp_is_zero
        )

        revenue_zero_gp_present_mask = (
            revenue_is_zero
            & ~gp_is_zero
        )

        safe_revenue = grouped_revenue.where(
            ~revenue_is_zero
        )

        margin_ratio = (
            grouped_gp
            .div(safe_revenue)
        )

        below_threshold_mask = (
            ~revenue_is_zero
            & margin_ratio.lt(threshold)
        )

        grouped[classification_column] = np.select(
            [
                both_zero_mask,
                revenue_zero_gp_present_mask,
                below_threshold_mask,
            ],
            [
                both_zero_result,
                revenue_zero_gp_present_result,
                below_threshold_result,
            ],
            default=pass_result,
        )

        # -----------------------------------------------------
        # Merge ONLY onto eligible rows
        # -----------------------------------------------------

        eligible_rows = (
            dataframe.loc[eligible_mask]
            .copy()
        )

        original_eligible_count = len(
            eligible_rows
        )

        try:
            enriched_eligible_rows = (
                eligible_rows.merge(
                    grouped,
                    how="left",
                    on=group_by,
                    validate="many_to_one",
                    sort=False,
                )
            )

        except Exception as exc:
            raise TransformationError(
                "Unable to merge grouped-margin "
                "classification back to eligible rows."
            ) from exc

        if (
            len(enriched_eligible_rows)
            != original_eligible_count
        ):
            raise TransformationError(
                "grouped_margin_enrichment changed "
                "the eligible row count from "
                f"{original_eligible_count} to "
                f"{len(enriched_eligible_rows)}."
            )

        # Preserve original dataframe index.
        enriched_eligible_rows.index = (
            dataframe.index[eligible_mask]
        )

        result.loc[
            eligible_mask,
            grouped_revenue_column,
        ] = enriched_eligible_rows[
            grouped_revenue_column
        ].to_numpy()

        result.loc[
            eligible_mask,
            grouped_gp_column,
        ] = enriched_eligible_rows[
            grouped_gp_column
        ].to_numpy()

        result.loc[
            eligible_mask,
            classification_column,
        ] = enriched_eligible_rows[
            classification_column
        ].to_numpy()

        return result

    def _gp_flag_classification(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Apply the transaction-level GP flag.

        A row receives the pass result when any condition is true:

        - Exception contains a value;
        - SBU is non-operational;
        - row is an SA material;
        - grouped margin classification is acceptable.

        Otherwise, the row receives the fail result.
        """

        del context

        inputs = definition.get("inputs", {})

        exception_column = inputs.get("exception")
        operational_sbu_column = inputs.get(
            "operational_sbu"
        )
        sa_materials_column = inputs.get(
            "sa_materials"
        )
        low_margin_column = inputs.get(
            "low_margin_flag"
        )

        required_columns = [
            operational_sbu_column,
            sa_materials_column,
            low_margin_column,
        ]

        if any(
            column is None
            for column in required_columns
        ):
            raise TransformationError(
                "gp_flag_classification requires "
                "operational_sbu, sa_materials, and "
                "low_margin_flag inputs."
            )

        self._require_columns(
            dataframe,
            required_columns,
        )

        allow_missing_exception = bool(
            definition.get(
                "allow_missing_exception",
                True,
            )
        )

        if (
            exception_column
            and exception_column
            not in dataframe.columns
            and not allow_missing_exception
        ):
            raise TransformationError(
                f"Configured exception column "
                f"{exception_column!r} does not exist."
            )

        result = dataframe.copy()

        if (
            exception_column
            and exception_column in result.columns
        ):
            exception_values = result[
                exception_column
            ]

            exception_mask = (
                exception_values.notna()
                & exception_values.astype("string")
                .str.strip()
                .ne("")
            )

        else:
            exception_mask = pd.Series(
                False,
                index=result.index,
            )

        non_operational_value = str(
            definition.get(
                "non_operational_value",
                "Non-Operational SBU",
            )
        ).strip().casefold()

        sa_material_value = str(
            definition.get(
                "sa_material_value",
                "SA Materials",
            )
        ).strip().casefold()

        acceptable_margin_value = str(
            definition.get(
                "acceptable_margin_value",
                "OK",
            )
        ).strip().casefold()

        operational_mask = (
            result[operational_sbu_column]
            .astype("string")
            .str.strip()
            .str.casefold()
            .eq(non_operational_value)
            .fillna(False)
        )

        sa_material_mask = (
            result[sa_materials_column]
            .astype("string")
            .str.strip()
            .str.casefold()
            .eq(sa_material_value)
            .fillna(False)
        )

        acceptable_margin_mask = (
            result[low_margin_column]
            .astype("string")
            .str.strip()
            .str.casefold()
            .eq(acceptable_margin_value)
            .fillna(False)
        )

        pass_mask = (
            exception_mask
            | operational_mask
            | sa_material_mask
            | acceptable_margin_mask
        ).fillna(False)

        result[definition["output"]] = np.where(
            pass_mask,
            definition.get(
                "pass_result",
                "OK",
            ),
            definition.get(
                "fail_result",
                "Not OK",
            ),
        )

        return result

    def _gp_flag_cam_classification(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Apply the CAM GP flag only to rows with a division node.

        Rows without a division node are not part of the CAM
        allocation population and therefore retain NULL gp_flag_cam.
        """

        inputs = definition.get(
            "inputs",
            {},
        )

        division_node_column = inputs.get(
            "division_node"
        )

        if not division_node_column:
            raise TransformationError(
                "gp_flag_cam_classification requires "
                "inputs.division_node."
            )

        self._require_columns(
            dataframe,
            [division_node_column],
        )

        result = dataframe.copy()

        output_column = definition["output"]

        result[output_column] = pd.NA

        division_values = (
            result[division_node_column]
            .astype("string")
            .str.strip()
        )

        applicable_mask = (
            result[division_node_column].notna()
            & division_values.ne("")
        ).fillna(False)

        if not applicable_mask.any():
            return result

        applicable_rows = (
            result.loc[applicable_mask]
            .copy()
        )

        classified_rows = self._gp_flag_classification(
            applicable_rows,
            definition,
            context,
        )

        result.loc[
            applicable_mask,
            output_column,
        ] = classified_rows[
            output_column
        ].to_numpy()

        return result
    
    def _nacs_fy25_eligibility_months(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        hire_date_column = inputs.get("hire_date")

        if not hire_date_column:
            raise TransformationError(
                "nacs_fy25_eligibility_months requires "
                "inputs.hire_date."
            )

        self._require_columns(
            dataframe,
            [hire_date_column],
        )

        quarter_definition = definition.get(
            "quarter",
            {},
        )

        cutoff_definition = definition.get(
            "cutoff_dates",
            {},
        )

        quarter = context.get_parameter(
            str(quarter_definition.get("parameter")),
            required=True,
        )

        cutoff_dates = context.get_parameter(
            str(cutoff_definition.get("parameter")),
            required=True,
        )

        quarter = str(quarter).upper()

        if quarter not in {
            "Q1",
            "Q2",
            "Q3",
            "Q4",
        }:
            raise TransformationError(
                f"Invalid NACS quarter: {quarter!r}."
            )

        required_cutoffs = [
            f"month_{month}"
            for month in range(1, 13)
        ]

        missing_cutoffs = [
            key
            for key in required_cutoffs
            if key not in cutoff_dates
        ]

        if missing_cutoffs:
            raise TransformationError(
                f"FY25 cutoff dates are missing: "
                f"{missing_cutoffs}"
            )

        resolved_cutoffs = {
            month: pd.Timestamp(
                cutoff_dates[f"month_{month}"]
            )
            for month in range(1, 13)
        }

        hire_dates = pd.to_datetime(
            dataframe[hire_date_column],
            errors="coerce",
        )

        result_values = pd.Series(
            pd.NA,
            index=dataframe.index,
            dtype="Int64",
        )

        quarter_allowed_months = {
            "Q1": {
                10,
                11,
                12,
            },
            "Q2": {
                7,
                8,
                9,
                10,
                11,
                12,
            },
            "Q3": {
                4,
                5,
                6,
                7,
                8,
                9,
                10,
                11,
                12,
            },
            "Q4": set(range(1, 13)),
        }

        for index, hire_date_value in hire_dates.items():
            if pd.isna(hire_date_value):
                continue

            eligible_months = 0

            if hire_date_value <= resolved_cutoffs[12]:
                eligible_months = 12
            else:
                for month in range(11, 0, -1):
                    lower_cutoff = resolved_cutoffs[
                        month + 1
                    ]
                    upper_cutoff = resolved_cutoffs[
                        month
                    ]

                    if (
                        hire_date_value > lower_cutoff
                        and hire_date_value <= upper_cutoff
                    ):
                        eligible_months = month
                        break

            if (
                eligible_months
                not in quarter_allowed_months[quarter]
            ):
                eligible_months = 0

            result_values.loc[index] = eligible_months

        result = dataframe.copy()
        result[definition["output"]] = result_values

        return result  

    def _nacs_fy26_eligibility_months(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        hire_date_column = inputs.get("hire_date")
        fy25_months_column = inputs.get("fy25_months")

        if not hire_date_column or not fy25_months_column:
            raise TransformationError(
                "nacs_fy26_eligibility_months requires "
                "hire_date and fy25_months."
            )

        self._require_columns(
            dataframe,
            [
                hire_date_column,
                fy25_months_column,
            ],
        )

        cutoff_definition = definition.get(
            "cutoff_dates",
            {},
        )

        cutoff_dates = context.get_parameter(
            str(cutoff_definition.get("parameter")),
            required=True,
        )

        required_cutoffs = [
            f"month_{month}"
            for month in range(1, 13)
        ]

        missing_cutoffs = [
            key
            for key in required_cutoffs
            if key not in cutoff_dates
        ]

        if missing_cutoffs:
            raise TransformationError(
                f"FY26 cutoff dates are missing: "
                f"{missing_cutoffs}"
            )

        resolved_cutoffs = {
            month: pd.Timestamp(
                cutoff_dates[f"month_{month}"]
            )
            for month in range(1, 13)
        }

        hire_dates = pd.to_datetime(
            dataframe[hire_date_column],
            errors="coerce",
        )

        fy25_months = pd.to_numeric(
            dataframe[fy25_months_column],
            errors="coerce",
        ).fillna(0)

        result_values = pd.Series(
            pd.NA,
            index=dataframe.index,
            dtype="Int64",
        )

        for index, hire_date_value in hire_dates.items():
            if pd.isna(hire_date_value):
                continue

            base_months = 0

            if hire_date_value <= resolved_cutoffs[12]:
                base_months = 12
            else:
                for month in range(11, 0, -1):
                    lower_cutoff = resolved_cutoffs[
                        month + 1
                    ]
                    upper_cutoff = resolved_cutoffs[
                        month
                    ]

                    if (
                        hire_date_value > lower_cutoff
                        and hire_date_value <= upper_cutoff
                    ):
                        base_months = month
                        break

            result_values.loc[index] = (
                base_months
                - int(fy25_months.loc[index])
            )

        result = dataframe.copy()
        result[definition["output"]] = result_values

        return result

    def _nacs_quarter_eligibility_months(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        total_months_column = inputs.get(
            "total_months"
        )

        previous_quarters = inputs.get(
            "previous_quarters",
            [],
        )

        if not total_months_column:
            raise TransformationError(
                "nacs_quarter_eligibility_months requires "
                "inputs.total_months."
            )

        if not isinstance(previous_quarters, list):
            raise TransformationError(
                "inputs.previous_quarters must be a list."
            )

        required_columns = [
            total_months_column,
            *previous_quarters,
        ]

        self._require_columns(
            dataframe,
            required_columns,
        )

        cap_value = definition.get(
            "cap_value",
            3,
        )

        cap_when_above = definition.get(
            "cap_when_above",
            3,
        )

        cap_when_at_or_below = definition.get(
            "cap_when_at_or_below"
        )

        if cap_when_at_or_below is None:
            raise TransformationError(
                "nacs_quarter_eligibility_months requires "
                "cap_when_at_or_below."
            )

        remaining = pd.to_numeric(
            dataframe[total_months_column],
            errors="coerce",
        )

        for previous_column in previous_quarters:
            remaining = (
                remaining
                - pd.to_numeric(
                    dataframe[previous_column],
                    errors="coerce",
                ).fillna(0)
            )

        should_cap = (
            remaining.gt(float(cap_when_above))
            & remaining.le(float(cap_when_at_or_below))
        )

        result_values = remaining.where(
            ~should_cap,
            float(cap_value),
        )

        result = dataframe.copy()
        result[definition["output"]] = result_values

        return result

    def _nacs_guarantee_status(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        inputs = definition.get(
            "inputs",
            {},
        )

        hire_date_column = inputs.get("hire_date")

        if not hire_date_column:
            raise TransformationError(
                "nacs_guarantee_status requires "
                "inputs.hire_date."
            )

        self._require_columns(
            dataframe,
            [hire_date_column],
        )

        quarter_definition = definition.get(
            "quarter",
            {},
        )

        check_dates_definition = definition.get(
            "check_dates",
            {},
        )

        duration_definition = definition.get(
            "guarantee_duration_days",
            {},
        )

        quarter = str(
            context.get_parameter(
                str(
                    quarter_definition.get(
                        "parameter"
                    )
                ),
                required=True,
            )
        ).upper()

        check_dates = context.get_parameter(
            str(
                check_dates_definition.get(
                    "parameter"
                )
            ),
            required=True,
        )

        guarantee_duration_days = int(
            context.get_parameter(
                str(
                    duration_definition.get(
                        "parameter"
                    )
                ),
                required=True,
            )
        )

        if quarter not in check_dates:
            raise TransformationError(
                f"No guarantee check date is configured "
                f"for quarter {quarter!r}."
            )

        check_date = pd.Timestamp(
            check_dates[quarter]
        )

        hire_dates = pd.to_datetime(
            dataframe[hire_date_column],
            errors="coerce",
        )

        crossed_value = definition.get(
            "crossed_value",
            "Crossed Gtee SIP",
        )

        eligible_value = definition.get(
            "eligible_value",
            "Eligible for Gtee SIP",
        )

        elapsed_days = (
            check_date - hire_dates
        ).dt.days

        result = dataframe.copy()

        result[definition["output"]] = np.where(
            hire_dates.isna(),
            None,
            np.where(
                elapsed_days > guarantee_duration_days,
                crossed_value,
                eligible_value,
            ),
        )

        return result                      
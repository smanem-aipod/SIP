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


class BaseAggregateOperation(BaseOperation):
    """
    Shared implementation for grouped calculations.
    """

    aggregation_function: str

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        source_dataset_name = definition.get(
            "source_dataset"
        )

        if source_dataset_name:
            source_frame = context.get_dataset(
                str(source_dataset_name)
            )
        else:
            source_frame = dataframe

        group_by = definition.get("group_by", [])
        source_keys = definition.get(
            "source_keys",
            group_by,
        )
        reference_keys = definition.get(
            "reference_keys",
            group_by,
        )

        if not isinstance(group_by, list) or not group_by:
            raise OperationExecutionError(
                f"{self.operation_name} requires group_by."
            )

        if len(source_keys) != len(reference_keys):
            raise OperationExecutionError(
                f"{self.operation_name} has mismatched "
                "source_keys and reference_keys."
            )

        self.require_columns(
            source_frame,
            group_by,
            dataset_name=str(
                source_dataset_name or "working_dataframe"
            ),
        )

        self.require_columns(
            dataframe,
            source_keys,
        )

        aggregated = self._aggregate(
            source_frame,
            definition,
            group_by=group_by,
        )

        return self._map_to_population(
            dataframe,
            aggregated,
            source_keys=source_keys,
            reference_keys=reference_keys,
            default=definition.get("default"),
        )

    def _aggregate(
        self,
        source_frame: pd.DataFrame,
        definition: dict[str, Any],
        *,
        group_by: list[str],
    ) -> pd.DataFrame:
        value_column = definition.get("value_column")

        if not value_column:
            raise OperationExecutionError(
                f"{self.operation_name} requires value_column."
            )

        self.require_columns(
            source_frame,
            [value_column],
        )

        working = self._apply_filters(
            dataframe=source_frame,
            filters=definition.get("filters", {}),
        )

        working = working[
            group_by + [value_column]
        ].copy()

        working[value_column] = pd.to_numeric(
            working[value_column],
            errors="coerce",
        )

        grouped = working.groupby(
            group_by,
            dropna=False,
            as_index=False,
        )[value_column]

        if self.aggregation_function == "sum":
            result = grouped.sum(
                min_count=1
            )

        elif self.aggregation_function == "mean":
            result = grouped.mean()

        elif self.aggregation_function == "minimum":
            result = grouped.min()

        elif self.aggregation_function == "maximum":
            result = grouped.max()

        else:
            raise OperationExecutionError(
                f"Unsupported aggregation function: "
                f"{self.aggregation_function!r}."
            )

        return result.rename(
            columns={
                value_column: "__aggregate_value",
            }
        )

    @classmethod
    def _apply_filters(
        cls,
        *,
        dataframe: pd.DataFrame,
        filters: dict[str, Any] | None,
    ) -> pd.DataFrame:
        """
        Apply configured source-row filters before aggregation.

        Example YAML:

            filters:
              exceptions:
                operator: equals
                value: "ok"
        """

        if not filters:
            return dataframe.copy()

        if not isinstance(filters, dict):
            raise OperationExecutionError(
                "Aggregation filters must be a dictionary."
            )

        result = dataframe.copy()

        for column_name, filter_definition in filters.items():
            cls.require_columns(
                result,
                [column_name],
            )

            if not isinstance(filter_definition, dict):
                filter_definition = {
                    "operator": "equals",
                    "value": filter_definition,
                }

            operator = str(
                filter_definition.get(
                    "operator",
                    "equals",
                )
            ).strip().lower()

            value = filter_definition.get("value")
            series = result[column_name]

            if operator == "equals":
                mask = series.eq(value)

            elif operator == "not_equals":
                mask = series.ne(value)

            elif operator == "in":
                values = (
                    value
                    if isinstance(value, list)
                    else [value]
                )
                mask = series.isin(values)

            elif operator == "not_in":
                values = (
                    value
                    if isinstance(value, list)
                    else [value]
                )
                mask = ~series.isin(values)

            elif operator == "is_null":
                mask = series.isna()

            elif operator == "not_null":
                mask = series.notna()

            elif operator == "greater_than":
                mask = series.gt(value)

            elif operator == "greater_than_or_equal":
                mask = series.ge(value)

            elif operator == "less_than":
                mask = series.lt(value)

            elif operator == "less_than_or_equal":
                mask = series.le(value)

            else:
                raise OperationExecutionError(
                    f"Unsupported aggregation filter "
                    f"operator: {operator!r}."
                )

            result = result.loc[
                mask.fillna(False)
            ].copy()

        return result

    @staticmethod
    def _map_to_population(
        dataframe: pd.DataFrame,
        aggregated: pd.DataFrame,
        *,
        source_keys: list[str],
        reference_keys: list[str],
        default: Any,
    ) -> pd.Series:
        left = dataframe[source_keys].copy()
        left["__row_position"] = range(len(left))

        merged = left.merge(
            aggregated,
            how="left",
            left_on=source_keys,
            right_on=reference_keys,
            validate="many_to_one",
            sort=False,
        )

        merged = merged.sort_values(
            "__row_position"
        )

        result = pd.Series(
            merged["__aggregate_value"].to_numpy(),
            index=dataframe.index,
        )

        if default is not None:
            result = result.fillna(default)

        return result


class AggregateSumOperation(BaseAggregateOperation):
    operation_name = "aggregate_sum"
    aggregation_function = "sum"


class AggregateAverageOperation(BaseAggregateOperation):
    operation_name = "aggregate_average"
    aggregation_function = "mean"


class AggregateMinimumOperation(BaseAggregateOperation):
    operation_name = "aggregate_minimum"
    aggregation_function = "minimum"


class AggregateMaximumOperation(BaseAggregateOperation):
    operation_name = "aggregate_maximum"
    aggregation_function = "maximum"


class AggregateCountOperation(BaseAggregateOperation):
    operation_name = "aggregate_count"

    def _aggregate(
        self,
        source_frame: pd.DataFrame,
        definition: dict[str, Any],
        *,
        group_by: list[str],
    ) -> pd.DataFrame:
        value_column = definition.get("value_column")

        if not value_column:
            raise OperationExecutionError(
                f"{self.operation_name} requires value_column."
            )

        self.require_columns(
            source_frame,
            group_by + [value_column],
        )

        working = self._apply_filters(
            dataframe=source_frame,
            filters=definition.get("filters", {}),
        )

        working = working[
            group_by + [value_column]
        ].copy()

        working[value_column] = pd.to_numeric(
            working[value_column],
            errors="coerce",
        )

        grouped = working.groupby(
            group_by,
            dropna=False,
            as_index=False,
        )[value_column]

        if self.aggregation_function == "sum":
            result = grouped.sum(
                min_count=1
            )

        elif self.aggregation_function == "mean":
            result = grouped.mean()

        elif self.aggregation_function == "minimum":
            result = grouped.min()

        elif self.aggregation_function == "maximum":
            result = grouped.max()

        else:
            raise OperationExecutionError(
                f"Unsupported aggregation function: "
                f"{self.aggregation_function!r}."
            )

        return result.rename(
            columns={
                value_column: "__aggregate_value",
            }
        )


class WeightedAverageOperation(BaseAggregateOperation):
    operation_name = "weighted_average"

    def _aggregate(
        self,
        source_frame: pd.DataFrame,
        definition: dict[str, Any],
        *,
        group_by: list[str],
    ) -> pd.DataFrame:
        value_column = definition.get("value_column")
        weight_column = definition.get("weight_column")

        if not value_column or not weight_column:
            raise OperationExecutionError(
                "weighted_average requires value_column "
                "and weight_column."
            )

        self.require_columns(
            source_frame,
            [
                value_column,
                weight_column,
            ],
        )

        working = source_frame[
            group_by
            + [
                value_column,
                weight_column,
            ]
        ].copy()
        values = pd.to_numeric(
            working[value_column],
            errors="coerce",
        )

        weights = pd.to_numeric(
            working[weight_column],
            errors="coerce",
        )

        working["__weighted_value"] = (
            values * weights
        )
        working["__valid_weight"] = weights.where(
            values.notna()
        )

        grouped = (
            working.groupby(
                group_by,
                dropna=False,
            )[
                [
                    "__weighted_value",
                    "__valid_weight",
                ]
            ]
            .sum(min_count=1)
            .reset_index()
        )

        denominator = grouped[
            "__valid_weight"
        ].where(
            grouped["__valid_weight"].ne(0)
        )

        grouped["__aggregate_value"] = (
            grouped["__weighted_value"]
            .div(denominator)
        )

        return grouped[
            group_by + ["__aggregate_value"]
        ]


class WeightedAllocationSumOperation(BaseOperation):
    """
    Allocate grouped actuals to an employee/entity using that
    entity's share of BP target within each allocation group.

    CAM example:
        BP:
            cam_id + division_node -> target

        allocation ratio:
            CAM target for division
            /
            total target for division

        Sales:
            division_node -> actual

        allocated actual:
            division actual * CAM ratio

        final:
            sum allocated actual by cam_id
            map cam_id back to employee_id
    """

    operation_name = "weighted_allocation_sum"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:

        source_dataset_name = definition.get(
            "source_dataset"
        )

        allocation_dataset_name = definition.get(
            "allocation_dataset"
        )

        population_key = definition.get(
            "population_key",
            "employee_id",
        )

        allocation_entity_key = definition.get(
            "allocation_entity_key"
        )

        allocation_group_key = definition.get(
            "allocation_group_key"
        )

        source_group_key = definition.get(
            "source_group_key"
        )

        value_column = definition.get(
            "value_column"
        )

        weight_column = definition.get(
            "weight_column"
        )

        if not source_dataset_name:
            raise OperationExecutionError(
                "weighted_allocation_sum requires "
                "source_dataset."
            )

        if not allocation_dataset_name:
            raise OperationExecutionError(
                "weighted_allocation_sum requires "
                "allocation_dataset."
            )

        required_config = {
            "allocation_entity_key": allocation_entity_key,
            "allocation_group_key": allocation_group_key,
            "source_group_key": source_group_key,
            "value_column": value_column,
            "weight_column": weight_column,
        }

        missing_config = [
            key
            for key, value in required_config.items()
            if not value
        ]

        if missing_config:
            raise OperationExecutionError(
                "weighted_allocation_sum is missing "
                f"configuration: {missing_config}."
            )

        source_frame = context.get_dataset(
            str(source_dataset_name)
        ).copy()

        allocation_frame = context.get_dataset(
            str(allocation_dataset_name)
        ).copy()

        self.require_columns(
            dataframe,
            [population_key],
            dataset_name="working_dataframe",
        )

        self.require_columns(
            source_frame,
            [
                source_group_key,
                value_column,
            ],
            dataset_name=str(source_dataset_name),
        )

        self.require_columns(
            allocation_frame,
            [
                allocation_entity_key,
                allocation_group_key,
                weight_column,
            ],
            dataset_name=str(allocation_dataset_name),
        )

        # ---------------------------------------------------
        # Apply source filters.
        # Example:
        # gp_flag_cam == OK
        # ---------------------------------------------------

        source_frame = (
            BaseAggregateOperation._apply_filters(
                dataframe=source_frame,
                filters=definition.get(
                    "filters",
                    {},
                ),
            )
        )

        # ---------------------------------------------------
        # Clean join keys
        # ---------------------------------------------------

        for frame, columns in (
            (
                source_frame,
                [source_group_key],
            ),
            (
                allocation_frame,
                [
                    allocation_entity_key,
                    allocation_group_key,
                ],
            ),
        ):
            for column_name in columns:
                frame[column_name] = (
                    frame[column_name]
                    .astype("string")
                    .str.strip()
                )

        # ---------------------------------------------------
        # Keep ALL target rows that have a division.
        #
        # Rows with no CAM ID still contribute to the
        # division's total target, but cannot receive an
        # allocation themselves.
        # ---------------------------------------------------

        allocation_frame = allocation_frame.loc[
            allocation_frame[
                allocation_group_key
            ].notna()
        ].copy()

        allocation_frame[weight_column] = pd.to_numeric(
            allocation_frame[weight_column],
            errors="coerce",
        )

        # ---------------------------------------------------
        # Total BP target for the entire division.
        #
        # IMPORTANT:
        # Includes rows where CAM ID is NULL.
        # ---------------------------------------------------

        division_totals = (
            allocation_frame.groupby(
                allocation_group_key,
                as_index=False,
                dropna=False,
            )[weight_column]
            .sum(min_count=1)
            .rename(
                columns={
                    weight_column:
                        "__allocation_group_total",
                }
            )
        )

        # ---------------------------------------------------
        # Target belonging to an identifiable CAM.
        #
        # NULL CAM rows do not receive actuals.
        # ---------------------------------------------------

        assigned_targets = allocation_frame.loc[
            allocation_frame[
                allocation_entity_key
            ].notna()
        ].copy()

        entity_group_targets = (
            assigned_targets.groupby(
                [
                    allocation_entity_key,
                    allocation_group_key,
                ],
                as_index=False,
                dropna=False,
            )[weight_column]
            .sum(min_count=1)
        )

        # ---------------------------------------------------
        # Attach FULL division target to each CAM.
        # ---------------------------------------------------

        entity_group_targets = (
            entity_group_targets.merge(
                division_totals,
                how="left",
                on=allocation_group_key,
                validate="many_to_one",
                sort=False,
            )
        )

        denominator = entity_group_targets[
            "__allocation_group_total"
        ].where(
            entity_group_targets[
                "__allocation_group_total"
            ].ne(0)
        )

        entity_group_targets[
            "__allocation_ratio"
        ] = (
            entity_group_targets[weight_column]
            .div(denominator)
        )

        # Apply CAM allocation overrides when present.
        # Only affects rows where cam_id + division_node match an override.
        # When division_node is None/blank in the override, applies to all
        # divisions for that cam_id.
        if (
            context.cam_allocation_overrides is not None
            and not context.cam_allocation_overrides.empty
        ):
            pct_col = (
                "allocation_pct_rev"
                if "rev" in str(weight_column).lower()
                else "allocation_pct_gp"
            )
            ov = context.cam_allocation_overrides[
                context.cam_allocation_overrides[pct_col].notna()
            ]
            for _, row in ov.iterrows():
                cam = str(row["cam_id"]).strip()
                div = row.get("division_node")
                pct = float(row[pct_col]) / 100.0
                mask = (
                    entity_group_targets[allocation_entity_key]
                    .astype(str).str.strip() == cam
                )
                if div and str(div).strip():
                    mask &= (
                        entity_group_targets[allocation_group_key]
                        .astype(str).str.strip() == str(div).strip()
                    )
                entity_group_targets.loc[mask, "__allocation_ratio"] = pct

        # ---------------------------------------------------
        # Sales actual per division.
        # ---------------------------------------------------

        source_frame[value_column] = pd.to_numeric(
            source_frame[value_column],
            errors="coerce",
        )

        actual_by_group = (
            source_frame.groupby(
                source_group_key,
                as_index=False,
                dropna=False,
            )[value_column]
            .sum(min_count=1)
            .rename(
                columns={
                    value_column: "__group_actual",
                }
            )
        )

        # ---------------------------------------------------
        # Attach division actual to every CAM allocation.
        # ---------------------------------------------------

        allocated = entity_group_targets.merge(
            actual_by_group,
            how="left",
            left_on=allocation_group_key,
            right_on=source_group_key,
            validate="many_to_one",
            sort=False,
        )

        allocated["__allocated_actual"] = (
            allocated["__group_actual"]
            * allocated["__allocation_ratio"]
        )

        # ---------------------------------------------------
        # CAM can have any number of divisions.
        # Sum all allocated division actuals by CAM.
        # ---------------------------------------------------

        entity_actuals = (
            allocated.groupby(
                allocation_entity_key,
                as_index=False,
                dropna=False,
            )["__allocated_actual"]
            .sum(min_count=1)
            .rename(
                columns={
                    "__allocated_actual":
                        "__aggregate_value",
                }
            )
        )

        # ---------------------------------------------------
        # Match HR employee_id -> BP cam_id.
        # ---------------------------------------------------

        left = dataframe[
            [population_key]
        ].copy()

        left[population_key] = (
            left[population_key]
            .astype("string")
            .str.strip()
        )

        left["__row_position"] = range(
            len(left)
        )

        result_frame = left.merge(
            entity_actuals,
            how="left",
            left_on=population_key,
            right_on=allocation_entity_key,
            validate="many_to_one",
            sort=False,
        )

        result_frame = result_frame.sort_values(
            "__row_position"
        )

        result = pd.Series(
            result_frame[
                "__aggregate_value"
            ].to_numpy(),
            index=dataframe.index,
        )

        default = definition.get("default")

        if default is not None:
            result = result.fillna(default)

        return result
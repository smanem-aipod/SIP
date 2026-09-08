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
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


class LookupOperation(BaseOperation):
    operation_name = "lookup"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        dataset_name = definition.get("dataset")

        if not dataset_name:
            raise OperationExecutionError(
                "lookup requires dataset."
            )

        reference_frame = context.get_dataset(
            str(dataset_name)
        )

        source_keys = definition.get(
            "source_keys",
            [],
        )
        reference_keys = definition.get(
            "reference_keys",
            [],
        )
        value_column = definition.get(
            "value_column"
        )

        if not source_keys or not reference_keys:
            raise OperationExecutionError(
                "lookup requires source_keys and "
                "reference_keys."
            )

        if len(source_keys) != len(reference_keys):
            raise OperationExecutionError(
                "lookup source_keys and reference_keys "
                "must have equal lengths."
            )

        if not value_column:
            raise OperationExecutionError(
                "lookup requires value_column."
            )

        self.require_columns(
            dataframe,
            source_keys,
        )

        self.require_columns(
            reference_frame,
            reference_keys + [value_column],
            dataset_name=str(dataset_name),
        )

        reference_subset = reference_frame[
            reference_keys + [value_column]
        ].copy()

        cardinality = str(
            definition.get(
                "cardinality",
                "many_to_one",
            )
        )

        if cardinality in {
            "many_to_one",
            "one_to_one",
        }:
            duplicate_mask = (
                reference_subset.duplicated(
                    subset=reference_keys,
                    keep=False,
                )
            )

            if duplicate_mask.any():
                sample = (
                    reference_subset.loc[
                        duplicate_mask,
                        reference_keys,
                    ]
                    .head(5)
                    .to_dict(orient="records")
                )

                raise OperationExecutionError(
                    f"Lookup dataset {dataset_name!r} "
                    f"contains duplicate reference keys. "
                    f"Samples: {sample}."
                )

        left = dataframe[source_keys].copy()
        left["__row_position"] = range(len(left))

        reference_value_name = "__lookup_value"

        reference_subset = reference_subset.rename(
            columns={
                value_column: reference_value_name,
            }
        )

        validate = {
            "many_to_one": "many_to_one",
            "one_to_one": "one_to_one",
            "one_to_many": "one_to_many",
            "many_to_many": "many_to_many",
        }.get(cardinality)

        merged = left.merge(
            reference_subset,
            how=str(
                definition.get("join_type", "left")
            ),
            left_on=source_keys,
            right_on=reference_keys,
            validate=validate,
            sort=False,
        )

        merged = merged.sort_values(
            "__row_position"
        )

        if len(merged) != len(dataframe):
            raise OperationExecutionError(
                "Lookup changed the calculation population "
                "row count. Use a unique reference key or "
                "perform aggregation before lookup."
            )

        result = pd.Series(
            merged[reference_value_name].to_numpy(),
            index=dataframe.index,
        )

        if "default" in definition:
            result = result.fillna(
                definition.get("default")
            )

        return result


class ExistsOperation(BaseOperation):
    operation_name = "exists"

    def execute(
        self,
        dataframe: pd.DataFrame,
        definition: dict[str, Any],
        context: CalculationContext,
    ) -> pd.Series:
        dataset_name = definition.get("dataset")

        if not dataset_name:
            raise OperationExecutionError(
                "exists requires dataset."
            )

        reference_frame = context.get_dataset(
            str(dataset_name)
        )

        source_keys = definition.get(
            "source_keys",
            [],
        )
        reference_keys = definition.get(
            "reference_keys",
            [],
        )

        if len(source_keys) != len(reference_keys):
            raise OperationExecutionError(
                "exists source_keys and reference_keys "
                "must have equal lengths."
            )

        self.require_columns(
            dataframe,
            source_keys,
        )

        self.require_columns(
            reference_frame,
            reference_keys,
            dataset_name=str(dataset_name),
        )

        reference_subset = (
            reference_frame[reference_keys]
            .drop_duplicates()
            .copy()
        )

        left = dataframe[source_keys].copy()
        left["__row_position"] = range(len(left))

        reference_subset["__exists"] = True

        merged = left.merge(
            reference_subset,
            how="left",
            left_on=source_keys,
            right_on=reference_keys,
            validate="many_to_one",
            sort=False,
        )

        merged = merged.sort_values(
            "__row_position"
        )

        return pd.Series(
            merged["__exists"]
            .fillna(False)
            .astype(bool)
            .to_numpy(),
            index=dataframe.index,
        )
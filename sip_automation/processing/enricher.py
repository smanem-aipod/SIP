from __future__ import annotations

from typing import Any

import pandas as pd

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import EnrichmentError
from sip_automation.core.logging import get_logger
from sip_automation.core.run_context import RunContext
from sip_automation.database.canonical_repository import (
    CanonicalRepository,
)
from sip_automation.database.reference_repository import (
    ReferenceRepository,
)


logger = get_logger(__name__)


class EnrichmentEngine:
    """
    Apply configuration-driven reference-table joins.

    Enrichment adds referenced columns only. Derived arithmetic using
    enriched fields runs later in TransformationEngine.
    """

    def __init__(
        self,
        *,
        config: ConfigManager,
        reference_repository: ReferenceRepository,
        canonical_repository: CanonicalRepository,
    ) -> None:
        self.config = config
        self.reference_repository = (
            reference_repository
        )
        self.canonical_repository = (
            canonical_repository
        )

    def enrich(
        self,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        enrichments: list[dict[str, Any]] | None,
        context: RunContext,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        for enrichment in enrichments or []:
            if not isinstance(enrichment, dict):
                raise EnrichmentError(
                    f"Enrichment definition in "
                    f"{logical_table_name!r} must be an object."
                )

            if not enrichment.get("enabled", True):
                continue

            result = self._apply_enrichment(
                result,
                logical_table_name=logical_table_name,
                definition=enrichment,
                context=context,
            )

        return result

    def _apply_enrichment(
        self,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        enrichment_name = str(
            definition.get("name", "unnamed")
        )

        operation = str(
            definition.get(
                "operation",
                "join",
            )
        ).strip().lower()

        if operation == "conditional_assignment_aggregate":
            return self._conditional_assignment_aggregate(
                dataframe,
                logical_table_name=logical_table_name,
                definition=definition,
                context=context,
            )

        reference_definition = definition.get(
            "reference"
        )

        if not isinstance(reference_definition, dict):
            raise EnrichmentError(
                f"Enrichment {enrichment_name!r} must define "
                f"a reference."
            )

        reference_layer = reference_definition.get(
            "layer"
        )

        reference_object = reference_definition.get(
            "object"
        )

        if not reference_layer or not reference_object:
            raise EnrichmentError(
                f"Enrichment {enrichment_name!r} reference must "
                f"define layer and object."
            )

        reference_filters = (
            self._resolve_runtime_values(
                definition.get(
                    "reference_filters",
                    {},
                ),
                context=context,
            )
        )

        reference_frame = self._read_reference(
            layer=str(reference_layer),
            object_name=str(reference_object),
            filters=reference_filters,
        )

        join_definition = definition.get(
            "join",
            {},
        )

        source_keys = join_definition.get(
            "source_keys",
            [],
        )

        reference_keys = join_definition.get(
            "reference_keys",
            [],
        )

        if len(source_keys) != len(reference_keys):
            raise EnrichmentError(
                f"Enrichment {enrichment_name!r} has mismatched "
                f"source and reference key counts."
            )

        self._require_columns(
            dataframe,
            source_keys,
            dataset_name=logical_table_name,
        )

        self._require_columns(
            reference_frame,
            reference_keys,
            dataset_name=(
                f"{reference_layer}.{reference_object}"
            ),
        )

        outputs = definition.get("outputs", {})

        required_reference_columns = set(
            reference_keys
        )

        for output_definition in outputs.values():
            if not isinstance(output_definition, dict):
                continue

            source_column = output_definition.get(
                "source_column"
            )

            if source_column:
                required_reference_columns.add(
                    str(source_column)
                )

        missing_output_columns = sorted(
            required_reference_columns
            - set(reference_frame.columns)
        )

        if missing_output_columns:
            raise EnrichmentError(
                f"Reference dataset "
                f"{reference_layer}.{reference_object} is missing "
                f"configured output columns: "
                f"{missing_output_columns}"
            )

        reference_subset = reference_frame[
            list(required_reference_columns)
        ].copy()

        cardinality = join_definition.get(
            "cardinality"
        )

        if cardinality == "many_to_one":
            duplicate_mask = (
                reference_subset.duplicated(
                    subset=reference_keys,
                    keep=False,
                )
            )

            if duplicate_mask.any():
                raise EnrichmentError(
                    f"Reference dataset "
                    f"{reference_layer}.{reference_object} contains "
                    f"duplicate join keys for enrichment "
                    f"{enrichment_name!r}."
                )

        rename_map: dict[str, str] = {}

        for output_column, output_definition in (
            outputs.items()
        ):
            if not isinstance(output_definition, dict):
                continue

            source_column = output_definition.get(
                "source_column"
            )

            if source_column:
                rename_map[str(source_column)] = (
                    output_column
                )

        reference_subset = reference_subset.rename(
            columns=rename_map
        )

        renamed_reference_keys = [
            rename_map.get(key, key)
            for key in reference_keys
        ]

        merge_validate = {
            "many_to_one": "many_to_one",
            "one_to_one": "one_to_one",
            "one_to_many": "one_to_many",
            "many_to_many": "many_to_many",
        }.get(cardinality)

        try:
            merged = dataframe.merge(
                reference_subset,
                how=str(
                    join_definition.get(
                        "type",
                        "left",
                    )
                ),
                left_on=source_keys,
                right_on=renamed_reference_keys,
                validate=merge_validate,
                indicator="_enrichment_match",
                suffixes=("", "__reference"),
            )

        except Exception as exc:
            raise EnrichmentError(
                f"Join failed for enrichment "
                f"{enrichment_name!r} on table "
                f"{logical_table_name!r}."
            ) from exc

        matched_mask = (
            merged["_enrichment_match"] == "both"
        )

        for output_column, output_definition in (
            outputs.items()
        ):
            if not isinstance(output_definition, dict):
                continue

            operation = output_definition.get(
                "operation"
            )

            if operation == "match_status":
                merged[output_column] = (
                    matched_mask.map(
                        {
                            True: output_definition.get(
                                "matched_value",
                                "Yes",
                            ),
                            False: output_definition.get(
                                "unmatched_value",
                                "No",
                            ),
                        }
                    )
                )

                continue

            if "source_column" not in output_definition:
                continue

            overwrite_existing = bool(
                output_definition.get(
                    "overwrite_existing",
                    True,
                )
            )

            reference_column = output_column

            alternative_reference_column = (
                f"{output_column}__reference"
            )

            if (
                alternative_reference_column
                in merged.columns
            ):
                reference_column = (
                    alternative_reference_column
                )

            if (
                output_column in dataframe.columns
                and not overwrite_existing
            ):
                merged[output_column] = (
                    merged[output_column]
                    .combine_first(
                        merged[reference_column]
                    )
                )

                if reference_column != output_column:
                    merged = merged.drop(
                        columns=[reference_column],
                        errors="ignore",
                    )

            elif reference_column != output_column:
                merged[output_column] = (
                    merged[reference_column]
                )

                merged = merged.drop(
                    columns=[reference_column],
                    errors="ignore",
                )

        columns_to_drop = [
            "_enrichment_match",
        ]

        for source_key, reference_key in zip(
            source_keys,
            renamed_reference_keys,
            strict=True,
        ):
            if (
                source_key != reference_key
                and reference_key in merged.columns
            ):
                columns_to_drop.append(reference_key)

        merged = merged.drop(
            columns=columns_to_drop,
            errors="ignore",
        )

        temporary_columns = [
            output_column
            for output_column, output_definition
            in outputs.items()
            if isinstance(output_definition, dict)
            and output_definition.get(
                "temporary",
                False,
            )
        ]

        match_rate = (
            float(matched_mask.mean())
            if len(matched_mask)
            else 0.0
        )

        logger.info(
            "enrichment_completed",
            logical_table_name=logical_table_name,
            enrichment_name=enrichment_name,
            reference_layer=reference_layer,
            reference_object=reference_object,
            row_count=len(merged),
            match_rate=round(match_rate, 6),
            temporary_columns=temporary_columns,
        )

        return merged

    def _read_reference(
        self,
        *,
        layer: str,
        object_name: str,
        filters: dict[str, Any] | None,
    ) -> pd.DataFrame:
        if layer == "reference":
            return self.reference_repository.read(
                object_name,
                filters=filters or None,
            )

        if layer == "canonical":
            return self.canonical_repository.read(
                object_name,
                filters=filters or None,
            )

        raise EnrichmentError(
            f"Unsupported enrichment reference layer: "
            f"{layer!r}"
        )

    @classmethod
    def _resolve_runtime_values(
        cls,
        values: dict[str, Any],
        *,
        context: RunContext,
    ) -> dict[str, Any]:
        resolved: dict[str, Any] = {}

        # ---- OLD (v1): only supported runtime_parameter (context.parameters) ----
        # for key, definition in values.items():
        #     if (
        #         isinstance(definition, dict)
        #         and "runtime_parameter" in definition
        #     ):
        #         resolved[key] = context.get_parameter(
        #             str(
        #                 definition["runtime_parameter"]
        #             ),
        #             required=True,
        #         )
        #     else:
        #         resolved[key] = definition
        # ---- END OLD (v1) ----

        # ---- NEW (v2 change): added runtime_context support ----
        for key, definition in values.items():
            if (
                isinstance(definition, dict)
                and "runtime_parameter" in definition
            ):
                resolved[key] = context.get_parameter(
                    str(
                        definition["runtime_parameter"]
                    ),
                    required=True,
                )

            elif (
                isinstance(definition, dict)
                and "runtime_context" in definition
            ):  # v2 change
                # Scope a reference read to the current run, e.g.:
                #   reference_filters:
                #     pipeline_run_id:
                #       runtime_context: run_id
                # Restricted to a fixed allowlist of RunContext attributes
                # (not arbitrary getattr) so configuration cannot reach
                # into unrelated internals.
                resolved[key] = cls._resolve_runtime_context_attribute(
                    str(definition["runtime_context"]),
                    context=context,
                )

            else:
                resolved[key] = definition

        return resolved
        # ---- END NEW (v2 change) ----

    # ---- v2 change: new attribute + method, did not exist in v1 ----
    _RUNTIME_CONTEXT_ATTRIBUTES = frozenset(
        {
            "run_id",
            "initiated_by",
            "fiscal_year",
            "effective_start_date",
        }
    )

    @classmethod
    def _resolve_runtime_context_attribute(
        cls,
        attribute_name: str,
        *,
        context: RunContext,
    ) -> Any:
        if attribute_name not in cls._RUNTIME_CONTEXT_ATTRIBUTES:
            raise EnrichmentError(
                f"Unsupported runtime_context attribute: "
                f"{attribute_name!r}. Allowed values: "
                f"{sorted(cls._RUNTIME_CONTEXT_ATTRIBUTES)}"
            )

        return getattr(context, attribute_name)

    @staticmethod
    def _require_columns(
        dataframe: pd.DataFrame,
        columns: list[str],
        *,
        dataset_name: str,
    ) -> None:
        missing = sorted(
            set(columns) - set(dataframe.columns)
        )

        if missing:
            raise EnrichmentError(
                f"Dataset {dataset_name!r} is missing "
                f"join columns: {missing}"
            )

    def _conditional_assignment_aggregate(
        self,
        dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        definition: dict[str, Any],
        context: RunContext,
    ) -> pd.DataFrame:
        """
        Aggregate a canonical reference dataset using:

        - mandatory matching columns;
        - optional matching columns that only participate when
        populated on the assignment row;
        - optional percentage sharing;
        - independent output filters.

        Designed for BDM assignment files but intentionally generic.
        """

        result = dataframe.copy()

        reference_definition = definition.get(
            "reference",
            {},
        )

        reference_layer = reference_definition.get(
            "layer"
        )

        reference_object = reference_definition.get(
            "object"
        )

        if not reference_layer or not reference_object:
            raise EnrichmentError(
                "conditional_assignment_aggregate requires "
                "reference.layer and reference.object."
            )

        reference_filters = {}

        if str(reference_layer).lower() == "canonical":
            reference_filters["pipeline_run_id"] = str(
                context.run_id
            )

        reference_frame = self._read_reference(
            layer=str(reference_layer),
            object_name=str(reference_object),
            filters=reference_filters,
        ).copy()

        matching = definition.get(
            "matching",
            {},
        )

        required_matches = matching.get(
            "required",
            [],
        )

        optional_matches = matching.get(
            "optional",
            [],
        )

        if not required_matches:
            raise EnrichmentError(
                "conditional_assignment_aggregate requires "
                "at least one required match."
            )

        source_required_columns = [
            item["source_column"]
            for item in required_matches
        ]

        reference_required_columns = [
            item["reference_column"]
            for item in required_matches
        ]

        source_optional_columns = [
            item["source_column"]
            for item in optional_matches
        ]

        reference_optional_columns = [
            item["reference_column"]
            for item in optional_matches
        ]

        self._require_columns(
            result,
            (
                source_required_columns
                + source_optional_columns
            ),
            dataset_name=logical_table_name,
        )

        self._require_columns(
            reference_frame,
            (
                reference_required_columns
                + reference_optional_columns
            ),
            dataset_name=(
                f"{reference_layer}.{reference_object}"
            ),
        )

        # -----------------------------------------------------
        # Normalize matching keys
        # -----------------------------------------------------

        for column_name in (
            source_required_columns
            + source_optional_columns
        ):
            result[column_name] = (
                result[column_name]
                .astype("string")
                .str.strip()
                .replace("", pd.NA)
            )

        for column_name in (
            reference_required_columns
            + reference_optional_columns
        ):
            reference_frame[column_name] = (
                reference_frame[column_name]
                .astype("string")
                .str.strip()
                .replace("", pd.NA)
            )

        sharing_definition = definition.get(
            "sharing",
            {},
        )

        sharing_column = sharing_definition.get(
            "column"
        )

        default_sharing = float(
            sharing_definition.get(
                "default",
                1.0,
            )
        )

        if sharing_column:
            self._require_columns(
                result,
                [sharing_column],
                dataset_name=logical_table_name,
            )

        outputs = definition.get(
            "outputs",
            {},
        )

        if not isinstance(outputs, dict) or not outputs:
            raise EnrichmentError(
                "conditional_assignment_aggregate requires outputs."
            )

        for output_column, output_definition in outputs.items():

            value_column = output_definition.get(
                "source_column"
            )

            if not value_column:
                raise EnrichmentError(
                    f"Output {output_column!r} requires "
                    "source_column."
                )

            self._require_columns(
                reference_frame,
                [value_column],
                dataset_name=(
                    f"{reference_layer}.{reference_object}"
                ),
            )

            filtered_reference = (
                self._apply_reference_filters(
                    reference_frame,
                    output_definition.get(
                        "filters",
                        {},
                    ),
                )
            )

            filtered_reference[value_column] = (
                pd.to_numeric(
                    filtered_reference[value_column],
                    errors="coerce",
                )
            )

            output_values = pd.Series(
                pd.NA,
                index=result.index,
                dtype="Float64",
            )

            # -------------------------------------------------
            # Rows can have different matching grains.
            #
            # Example:
            # ship_to only
            # ship_to + profitcenter
            # ship_to + material
            # ship_to + profitcenter + material
            # -------------------------------------------------

            optional_presence = pd.DataFrame(
                {
                    item["source_column"]:
                        result[
                            item["source_column"]
                        ].notna()
                    for item in optional_matches
                },
                index=result.index,
            )

            if optional_presence.empty:
                signatures = pd.Series(
                    [tuple()] * len(result),
                    index=result.index,
                )
            else:
                signatures = optional_presence.apply(
                    lambda row: tuple(
                        column_name
                        for column_name, present
                        in row.items()
                        if bool(present)
                    ),
                    axis=1,
                )

            for signature in signatures.unique():

                assignment_mask = signatures.apply(
                    lambda value: value == signature
                )

                assignment_subset = (
                    result.loc[
                        assignment_mask
                    ]
                    .copy()
                )

                source_keys = list(
                    source_required_columns
                )

                reference_keys = list(
                    reference_required_columns
                )

                for item in optional_matches:
                    if (
                        item["source_column"]
                        in signature
                    ):
                        source_keys.append(
                            item["source_column"]
                        )

                        reference_keys.append(
                            item["reference_column"]
                        )

                grouped_reference = (
                    filtered_reference.groupby(
                        reference_keys,
                        dropna=False,
                        as_index=False,
                    )[value_column]
                    .sum(min_count=1)
                    .rename(
                        columns={
                            value_column:
                                "__aggregate_value",
                        }
                    )
                )

                left = assignment_subset[
                    source_keys
                ].copy()

                left["__row_index"] = (
                    assignment_subset.index
                )

                matched = left.merge(
                    grouped_reference,
                    how="left",
                    left_on=source_keys,
                    right_on=reference_keys,
                    validate="many_to_one",
                    sort=False,
                )

                matched = matched.set_index(
                    "__row_index"
                )

                values = pd.to_numeric(
                    matched["__aggregate_value"],
                    errors="coerce",
                )

                if sharing_column:
                    sharing = pd.to_numeric(
                        result.loc[
                            values.index,
                            sharing_column,
                        ],
                        errors="coerce",
                    ).fillna(default_sharing)

                    values = values * sharing

                output_values.loc[
                    values.index
                ] = values

            result[output_column] = output_values

        logger.info(
            "conditional_assignment_aggregate_completed",
            logical_table_name=logical_table_name,
            reference_object=str(reference_object),
            row_count=len(result),
            output_columns=list(outputs),
        )

        return result

    @staticmethod
    def _apply_reference_filters(
        dataframe: pd.DataFrame,
        filters: dict[str, Any] | None,
    ) -> pd.DataFrame:

        if not filters:
            return dataframe.copy()

        result = dataframe.copy()

        for column_name, filter_definition in (
            filters.items()
        ):
            if column_name not in result.columns:
                raise EnrichmentError(
                    f"Reference filter column "
                    f"{column_name!r} does not exist."
                )

            if not isinstance(
                filter_definition,
                dict,
            ):
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

            value = filter_definition.get(
                "value"
            )

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

            else:
                raise EnrichmentError(
                    f"Unsupported reference filter "
                    f"operator: {operator!r}."
                )

            result = result.loc[
                mask.fillna(False)
            ].copy()

        return result
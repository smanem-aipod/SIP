"""
Generic execution engine for SIP metrics.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from sip_automation.calculation_engine.context import (
    CalculationContext,
)
from sip_automation.calculation_engine.dependency_graph import (
    MetricDependencyGraph,
)
from sip_automation.calculation_engine.models import (
    MetricDefinition,
    ResolvedMetricPlan,
)
from sip_automation.calculation_engine.registry import (
    OperationRegistry,
)
from sip_automation.calculation_engine.validators import (
    MetricPlanValidator,
)
from sip_automation.core.logging import get_logger

logger = get_logger(__name__)


class MetricEngineExecutionError(RuntimeError):
    """
    Raised when the metric engine cannot complete execution.
    """


class MetricEngine:
    """
    Execute every enabled metric in dependency order.

    The working DataFrame begins with the selected employee
    population. Each executed metric is added as a new column.
    """

    def __init__(
        self,
        registry: OperationRegistry | None = None,
    ) -> None:
        self.registry = registry or OperationRegistry()

        self.validator = MetricPlanValidator(
            self.registry
        )

    def run(
        self,
        *,
        plan: ResolvedMetricPlan,
        context: CalculationContext,
        use_output_names: bool = True,
    ) -> pd.DataFrame:
        """
        Execute a resolved role-specific metric plan.
        """

        self.validator.validate(plan)

        runtime_context = self._build_runtime_context(
            plan=plan,
            context=context,
        )

        working_dataframe = self._build_population(
            plan=plan,
            context=runtime_context,
        )

        dependency_graph = MetricDependencyGraph(
            plan
        )

        for metric in dependency_graph.ordered_metrics():
            working_dataframe = self._execute_metric(
                dataframe=working_dataframe,
                metric=metric,
                context=runtime_context,
            )

        if use_output_names:
            working_dataframe = self._rename_metrics(
                dataframe=working_dataframe,
                plan=plan,
            )

        return working_dataframe

    def _execute_metric(
        self,
        *,
        dataframe: pd.DataFrame,
        metric: MetricDefinition,
        context: CalculationContext,
    ) -> pd.DataFrame:
        """
        Execute one metric and append the result as a column.
        """

        operation = self.registry.get(
            metric.operation
        )

        try:
            metric_result = operation.execute(
                dataframe,
                metric.definition,
                context,
            )

        except Exception as exc:
            raise MetricEngineExecutionError(
                f"Metric {metric.name!r} failed using "
                f"operation {metric.operation!r}."
            ) from exc

        if not isinstance(metric_result, pd.Series):
            raise MetricEngineExecutionError(
                f"Metric {metric.name!r} returned "
                f"{type(metric_result).__name__}; "
                "expected pandas.Series."
            )

        if len(metric_result) != len(dataframe):
            raise MetricEngineExecutionError(
                f"Metric {metric.name!r} returned "
                f"{len(metric_result)} rows, but the "
                f"population has {len(dataframe)} rows."
            )

        result = dataframe.copy()

        result[metric.name] = metric_result.reindex(
            result.index
        )

        return result

    @staticmethod
    def _build_runtime_context(
        *,
        plan: ResolvedMetricPlan,
        context: CalculationContext,
    ) -> CalculationContext:
        """
        Merge plan parameters and static references into context.

        Explicit values supplied by the runtime context override
        defaults from generic_metrics.yaml.
        """

        supplied_parameters = dict(
            context.parameters or {}
        )

        merged_parameters = {
            **plan.parameters,
            **supplied_parameters,
        }

        logger.info(
            "engine_build_runtime_context_debug",
            plan_parameters=plan.parameters,
            supplied_parameters=supplied_parameters,
            merged_parameters=merged_parameters,
            target_q2_multiplier_supplied=supplied_parameters.get("target_q2_multiplier"),
            target_q2_multiplier_merged=merged_parameters.get("target_q2_multiplier"),
        )

        quarter = (
            context.quarter
            if context.quarter is not None
            else merged_parameters.get("quarter")
        )

        fiscal_year = (
            context.fiscal_year
            if context.fiscal_year is not None
            else merged_parameters.get("fiscal_year")
        )

        return replace(
            context,
            quarter=quarter,
            fiscal_year=fiscal_year,
            parameters=merged_parameters,
            static_reference_data=(
                plan.static_reference_data
            ),
        )

    @staticmethod
    def _build_population(
        *,
        plan: ResolvedMetricPlan,
        context: CalculationContext,
    ) -> pd.DataFrame:
        """
        Select the role population from the configured dataset.
        """

        population = plan.population

        dataset_name = population.get("dataset")

        if not dataset_name:
            raise MetricEngineExecutionError(
                "population.dataset is required."
            )

        dataframe = context.get_dataset(
            str(dataset_name)
        ).copy()

        filters = population.get(
            "filters",
            {},
        )

        if not isinstance(filters, dict):
            raise MetricEngineExecutionError(
                "population.filters must be a dictionary."
            )

        for column_name, definition in filters.items():
            dataframe = MetricEngine._apply_population_filter(
                dataframe=dataframe,
                column_name=str(column_name),
                definition=definition,
            )

        return dataframe.reset_index(drop=True)

    @staticmethod
    def _apply_population_filter(
        *,
        dataframe: pd.DataFrame,
        column_name: str,
        definition,
    ) -> pd.DataFrame:
        """
        Apply one configured role-population filter.
        """

        if column_name not in dataframe.columns:
            raise MetricEngineExecutionError(
                f"Population filter column "
                f"{column_name!r} does not exist."
            )

        if not isinstance(definition, dict):
            definition = {
                "operator": "equals",
                "value": definition,
            }

        operator = str(
            definition.get(
                "operator",
                "equals",
            )
        ).strip().lower()

        value = definition.get("value")
        series = dataframe[column_name]

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
            raise MetricEngineExecutionError(
                f"Unsupported population-filter "
                f"operator: {operator!r}."
            )

        return dataframe.loc[
            mask.fillna(False)
        ].copy()

    @staticmethod
    def _rename_metrics(
        *,
        dataframe: pd.DataFrame,
        plan: ResolvedMetricPlan,
    ) -> pd.DataFrame:
        """
        Rename internal metric IDs to business-facing names.

        Canonical source columns remain unchanged.
        """

        rename_mapping = {
            metric.name: metric.output_name
            for metric in plan.metrics.values()
            if metric.name in dataframe.columns
        }

        duplicate_output_names = [
            output_name
            for output_name in rename_mapping.values()
            if output_name in dataframe.columns
            and output_name not in rename_mapping
        ]

        if duplicate_output_names:
            raise MetricEngineExecutionError(
                "Metric output names conflict with existing "
                f"canonical columns: "
                f"{sorted(duplicate_output_names)}."
            )

        return dataframe.rename(
            columns=rename_mapping
        )
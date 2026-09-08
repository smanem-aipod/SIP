"""
Configuration validation for the SIP metric engine.
"""

from __future__ import annotations

from typing import Any

from sip_automation.calculation_engine.models import (
    METRIC_SECTIONS,
    ResolvedMetricPlan,
)
from sip_automation.calculation_engine.registry import (
    OperationRegistry,
)


class MetricPlanValidationError(ValueError):
    """
    Raised when a resolved metric plan is invalid.
    """


class MetricPlanValidator:
    """
    Validate a fully resolved metric plan before execution.

    This validates configuration only. It does not inspect
    DataFrame values or execute calculations.
    """

    def __init__(
        self,
        registry: OperationRegistry,
    ) -> None:
        self.registry = registry

    def validate(
        self,
        plan: ResolvedMetricPlan,
    ) -> None:
        """
        Validate the complete resolved plan.

        Raises MetricPlanValidationError if any issue exists.
        """

        errors: list[str] = []

        errors.extend(
            self._validate_plan_metadata(plan)
        )
        errors.extend(
            self._validate_population(plan)
        )
        errors.extend(
            self._validate_metric_names(plan)
        )
        errors.extend(
            self._validate_operations(plan)
        )
        errors.extend(
            self._validate_role_placeholders(plan)
        )
        errors.extend(
            self._validate_explicit_dependencies(plan)
        )
        errors.extend(
            self._validate_metric_references(plan)
        )
        errors.extend(
            self._validate_output_names(plan)
        )

        if errors:
            formatted_errors = "\n".join(
                f"- {error}"
                for error in errors
            )

            raise MetricPlanValidationError(
                "Metric-plan validation failed:\n"
                f"{formatted_errors}"
            )

    # =====================================================
    # PLAN
    # =====================================================

    @staticmethod
    def _validate_plan_metadata(
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []

        if not plan.library_id.strip():
            errors.append(
                "library_id cannot be empty."
            )

        if not plan.role_id.strip():
            errors.append(
                "role_id cannot be empty."
            )

        if not plan.version.strip():
            errors.append(
                "version cannot be empty."
            )

        if not plan.metrics:
            errors.append(
                "The resolved plan contains no enabled metrics."
            )

        return errors

    # =====================================================
    # POPULATION
    # =====================================================

    @staticmethod
    def _validate_population(
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []

        population = plan.population

        if not isinstance(population, dict):
            return [
                "population must be a dictionary."
            ]

        dataset = population.get("dataset")

        if not dataset:
            errors.append(
                "population.dataset is required."
            )

        filters = population.get(
            "filters",
            {},
        )

        if not isinstance(filters, dict):
            errors.append(
                "population.filters must be a dictionary."
            )

        key_columns = population.get(
            "key_columns",
            [],
        )

        if not isinstance(key_columns, list):
            errors.append(
                "population.key_columns must be a list."
            )

        elif not key_columns:
            errors.append(
                "population.key_columns must contain "
                "at least one column."
            )

        return errors

    # =====================================================
    # METRIC NAMES
    # =====================================================

    @staticmethod
    def _validate_metric_names(
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []

        for metric_name, metric in plan.metrics.items():
            if not metric_name.strip():
                errors.append(
                    "Metric names cannot be empty."
                )
                continue

            if metric.name != metric_name:
                errors.append(
                    f"Metric dictionary key {metric_name!r} "
                    f"does not match metric.name "
                    f"{metric.name!r}."
                )

            if metric.section not in METRIC_SECTIONS:
                errors.append(
                    f"Metric {metric_name!r} has unknown "
                    f"section {metric.section!r}."
                )

        return errors

    # =====================================================
    # OPERATIONS
    # =====================================================

    def _validate_operations(
        self,
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []

        for metric_name, metric in plan.metrics.items():
            if not metric.operation.strip():
                errors.append(
                    f"Metric {metric_name!r} does not "
                    "define an operation."
                )

                continue

            if not self.registry.exists(
                metric.operation
            ):
                errors.append(
                    f"Metric {metric_name!r} uses unknown "
                    f"operation {metric.operation!r}. "
                    f"Registered operations: "
                    f"{self.registry.names()}."
                )

        return errors

    # =====================================================
    # ROLE MAPPING RESOLUTION
    # =====================================================

    @classmethod
    def _validate_role_placeholders(
        cls,
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []

        for metric_name, metric in plan.metrics.items():
            unresolved_paths = (
                cls._find_unresolved_role_mappings(
                    metric.definition
                )
            )

            for path in unresolved_paths:
                errors.append(
                    f"Metric {metric_name!r} still contains "
                    f"an unresolved role_mapping value at "
                    f"{path}."
                )

        return errors

    @classmethod
    def _find_unresolved_role_mappings(
        cls,
        value: Any,
        *,
        path: str = "definition",
    ) -> list[str]:
        unresolved: list[str] = []

        if isinstance(value, dict):
            if "role_mapping" in value:
                unresolved.append(path)

            for key, child_value in value.items():
                unresolved.extend(
                    cls._find_unresolved_role_mappings(
                        child_value,
                        path=f"{path}.{key}",
                    )
                )

        elif isinstance(value, list):
            for index, child_value in enumerate(value):
                unresolved.extend(
                    cls._find_unresolved_role_mappings(
                        child_value,
                        path=f"{path}[{index}]",
                    )
                )

        return unresolved

    # =====================================================
    # EXPLICIT DEPENDENCIES
    # =====================================================

    @staticmethod
    def _validate_explicit_dependencies(
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []

        metric_names = set(plan.metrics)

        for metric_name, metric in plan.metrics.items():
            for dependency in (
                metric.explicit_dependencies
            ):
                if dependency == metric_name:
                    errors.append(
                        f"Metric {metric_name!r} cannot "
                        "depend on itself."
                    )

                elif dependency not in metric_names:
                    errors.append(
                        f"Metric {metric_name!r} explicitly "
                        f"depends on unknown metric "
                        f"{dependency!r}."
                    )

        return errors

    # =====================================================
    # INFERRED METRIC REFERENCES
    # =====================================================

    @classmethod
    def _validate_metric_references(
        cls,
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        """
        Check references that clearly point to other metrics.

        Database/source column names are not validated here.
        They will be validated by the operation against the
        actual DataFrame during execution.
        """

        errors: list[str] = []
        metric_names = set(plan.metrics)

        for metric_name, metric in plan.metrics.items():
            references = cls.find_metric_references(
                metric.definition,
                known_metric_names=metric_names,
            )

            for reference in references:
                if reference == metric_name:
                    errors.append(
                        f"Metric {metric_name!r} references "
                        "itself."
                    )

        return errors

    @classmethod
    def find_metric_references(
        cls,
        definition: dict[str, Any],
        *,
        known_metric_names: set[str],
    ) -> set[str]:
        """
        Return configured values that reference another metric.

        Bare strings under inputs are treated as potential metric
        references only when they match a configured metric name.

        Explicit column operands such as:

            column: employee_id

        are intentionally ignored.
        """

        references: set[str] = set()

        cls._collect_metric_references(
            definition,
            known_metric_names=known_metric_names,
            references=references,
            parent_key=None,
        )

        return references

    @classmethod
    def _collect_metric_references(
        cls,
        value: Any,
        *,
        known_metric_names: set[str],
        references: set[str],
        parent_key: str | None,
    ) -> None:
        if isinstance(value, str):
            if (
                parent_key not in {
                    "operation",
                    "output_name",
                    "source_dataset",
                    "dataset",
                    "value_column",
                    "parameter",
                    "static_reference",
                    "operator",
                    "section",
                }
                and value in known_metric_names
            ):
                references.add(value)

            return

        if isinstance(value, list):
            for child_value in value:
                cls._collect_metric_references(
                    child_value,
                    known_metric_names=(
                        known_metric_names
                    ),
                    references=references,
                    parent_key=parent_key,
                )

            return

        if not isinstance(value, dict):
            return

        for key, child_value in value.items():
            if key == "depends_on":
                continue

            cls._collect_metric_references(
                child_value,
                known_metric_names=known_metric_names,
                references=references,
                parent_key=str(key),
            )

    # =====================================================
    # OUTPUT NAMES
    # =====================================================

    @staticmethod
    def _validate_output_names(
        plan: ResolvedMetricPlan,
    ) -> list[str]:
        errors: list[str] = []
        output_names: dict[str, str] = {}

        for metric_name, metric in plan.metrics.items():
            output_name = metric.output_name.strip()

            if not output_name:
                errors.append(
                    f"Metric {metric_name!r} has an empty "
                    "output_name."
                )

                continue

            previous_metric = output_names.get(
                output_name
            )

            if previous_metric:
                errors.append(
                    f"Metrics {previous_metric!r} and "
                    f"{metric_name!r} use the same "
                    f"output_name {output_name!r}."
                )

            else:
                output_names[output_name] = (
                    metric_name
                )

        return errors
"""
Dependency graph and execution ordering for configured metrics.
"""

from __future__ import annotations

from collections import deque

from sip_automation.calculation_engine.models import (
    MetricDefinition,
    ResolvedMetricPlan,
)
from sip_automation.calculation_engine.validators import (
    MetricPlanValidator,
)


class MetricDependencyError(ValueError):
    """
    Raised when metric dependencies are invalid or cyclic.
    """


class MetricDependencyGraph:
    """
    Build and sort metric dependencies.

    A dependency may be declared explicitly with:

        depends_on:
          - metric_name

    Or inferred when a configured metric name appears in another
    metric's inputs or definition.
    """

    def __init__(
        self,
        plan: ResolvedMetricPlan,
    ) -> None:
        self.plan = plan
        self.metrics = plan.metrics
        self.dependencies = self._build_dependencies()

    def _build_dependencies(
        self,
    ) -> dict[str, set[str]]:
        metric_names = set(self.metrics)

        graph: dict[str, set[str]] = {
            metric_name: set()
            for metric_name in metric_names
        }

        for metric_name, metric in self.metrics.items():
            graph[metric_name].update(
                metric.explicit_dependencies
            )

            inferred_dependencies = (
                MetricPlanValidator.find_metric_references(
                    metric.definition,
                    known_metric_names=metric_names,
                )
            )

            graph[metric_name].update(
                inferred_dependencies
            )

            graph[metric_name].discard(metric_name)

        self._validate_dependencies(graph)

        return graph

    @staticmethod
    def _validate_dependencies(
        graph: dict[str, set[str]],
    ) -> None:
        metric_names = set(graph)
        errors: list[str] = []

        for metric_name, dependencies in graph.items():
            unknown_dependencies = sorted(
                dependencies - metric_names
            )

            if unknown_dependencies:
                errors.append(
                    f"Metric {metric_name!r} depends on "
                    f"unknown metrics: {unknown_dependencies}."
                )

        if errors:
            raise MetricDependencyError(
                "\n".join(errors)
            )

    def execution_order(
        self,
    ) -> list[str]:
        """
        Return metric names in topological execution order.
        """

        dependency_count = {
            metric_name: len(dependencies)
            for metric_name, dependencies
            in self.dependencies.items()
        }

        dependents: dict[str, set[str]] = {
            metric_name: set()
            for metric_name in self.metrics
        }

        for metric_name, dependencies in (
            self.dependencies.items()
        ):
            for dependency in dependencies:
                dependents[dependency].add(
                    metric_name
                )

        ready = deque(
            metric_name
            for metric_name, count
            in dependency_count.items()
            if count == 0
        )

        ordered: list[str] = []

        while ready:
            metric_name = ready.popleft()
            ordered.append(metric_name)

            for dependent in sorted(
                dependents[metric_name]
            ):
                dependency_count[dependent] -= 1

                if dependency_count[dependent] == 0:
                    ready.append(dependent)

        if len(ordered) != len(self.metrics):
            cyclic_metrics = sorted(
                metric_name
                for metric_name, count
                in dependency_count.items()
                if count > 0
            )

            cycle_description = {
                metric_name: sorted(
                    self.dependencies[metric_name]
                )
                for metric_name in cyclic_metrics
            }

            raise MetricDependencyError(
                "Circular metric dependency detected. "
                f"Involved metrics: {cycle_description}."
            )

        return ordered

    def dependencies_for(
        self,
        metric_name: str,
    ) -> set[str]:
        try:
            return set(
                self.dependencies[metric_name]
            )

        except KeyError as exc:
            raise KeyError(
                f"Unknown metric: {metric_name!r}."
            ) from exc

    def ordered_metrics(
        self,
    ) -> list[MetricDefinition]:
        return [
            self.metrics[metric_name]
            for metric_name in self.execution_order()
        ]
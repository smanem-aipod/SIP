"""
Configuration models for the SIP metric and calculation engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


METRIC_SECTIONS: tuple[str, ...] = (
    "aggregation_metrics",
    "lookup_metrics",
    "derived_metrics",
    "rule_metrics",
    "calculations",
)


@dataclass(frozen=True)
class MetricDefinition:
    """
    One configured reusable metric.

    A metric may represent:

    - an aggregation;
    - a lookup;
    - an arithmetic calculation;
    - a conditional rule;
    - a final SIP calculation.

    The engine treats all of them as executable nodes.
    """

    name: str
    section: str
    operation: str
    enabled: bool
    publish: bool
    output_name: str
    definition: dict[str, Any]
    explicit_dependencies: tuple[str, ...] = ()

    @classmethod
    def from_config(
        cls,
        *,
        name: str,
        section: str,
        definition: dict[str, Any],
        quarter: str | None = None,
    ) -> "MetricDefinition":
        if not isinstance(definition, dict):
            raise ValueError(
                f"Metric {name!r} in section {section!r} "
                "must be a dictionary."
            )

        operation = definition.get("operation")

        if not operation:
            raise ValueError(
                f"Metric {name!r} in section {section!r} "
                "must define an operation."
            )

        dependencies = definition.get(
            "depends_on",
            [],
        )

        if isinstance(dependencies, str):
            dependencies = [dependencies]

        if not isinstance(dependencies, list):
            raise ValueError(
                f"Metric {name!r} depends_on must be "
                "a string or list."
            )

        output_name = str(
            definition.get(
                "output_name",
                name,
            )
        )

        # Lets a metric's display name/export header follow the run's
        # actual selected quarter (e.g. "Guarantee SIP ({quarter})")
        # instead of ever being hardcoded to a single quarter that goes
        # stale. Only substituted when both a placeholder and a resolved
        # quarter are present - otherwise the literal "{quarter}" text
        # is left as-is rather than raising, since not every caller
        # (e.g. the pre-role-binding pass) has a quarter to give.
        if "{quarter}" in output_name and quarter:
            output_name = output_name.format(quarter=quarter)

        return cls(
            name=str(name),
            section=str(section),
            operation=str(operation),
            enabled=bool(
                definition.get("enabled", True)
            ),
            publish=bool(
                definition.get("publish", False)
            ),
            output_name=output_name,
            definition=dict(definition),
            explicit_dependencies=tuple(
                str(dependency)
                for dependency in dependencies
            ),
        )


@dataclass(frozen=True)
class MetricLibrary:
    """
    Parsed generic metric-library configuration.

    This represents generic_metrics.yaml before a role mapping
    is applied.
    """

    library_id: str
    name: str
    version: str
    enabled: bool

    parameters: dict[str, Any] = field(
        default_factory=dict
    )

    static_reference_data: dict[str, Any] = field(
        default_factory=dict
    )

    aggregation_metrics: dict[
        str,
        MetricDefinition,
    ] = field(default_factory=dict)

    lookup_metrics: dict[
        str,
        MetricDefinition,
    ] = field(default_factory=dict)

    derived_metrics: dict[
        str,
        MetricDefinition,
    ] = field(default_factory=dict)

    rule_metrics: dict[
        str,
        MetricDefinition,
    ] = field(default_factory=dict)

    calculations: dict[
        str,
        MetricDefinition,
    ] = field(default_factory=dict)

    @classmethod
    def from_config(
        cls,
        config: dict[str, Any],
    ) -> "MetricLibrary":
        if not isinstance(config, dict):
            raise ValueError(
                "Metric-library configuration must be "
                "a dictionary."
            )

        library_definition = config.get(
            "library",
            {},
        )

        if not isinstance(
            library_definition,
            dict,
        ):
            raise ValueError(
                "generic_metrics.yaml must contain "
                "a library object."
            )

        library_id = library_definition.get(
            "library_id"
        )

        if not library_id:
            raise ValueError(
                "Metric library must define "
                "library.library_id."
            )

        sections = {
            section_name: cls._load_metric_section(
                config=config,
                section_name=section_name,
            )
            for section_name in METRIC_SECTIONS
        }

        return cls(
            library_id=str(library_id),
            name=str(
                library_definition.get(
                    "name",
                    library_id,
                )
            ),
            version=str(
                library_definition.get(
                    "version",
                    "1.0",
                )
            ),
            enabled=bool(
                library_definition.get(
                    "enabled",
                    True,
                )
            ),
            parameters=dict(
                config.get(
                    "parameters",
                    {},
                )
            ),
            static_reference_data=dict(
                config.get(
                    "static_reference_data",
                    {},
                )
            ),
            aggregation_metrics=sections[
                "aggregation_metrics"
            ],
            lookup_metrics=sections[
                "lookup_metrics"
            ],
            derived_metrics=sections[
                "derived_metrics"
            ],
            rule_metrics=sections[
                "rule_metrics"
            ],
            calculations=sections[
                "calculations"
            ],
        )

    @staticmethod
    def _load_metric_section(
        *,
        config: dict[str, Any],
        section_name: str,
    ) -> dict[str, MetricDefinition]:
        section = config.get(
            section_name,
            {},
        )

        if section is None:
            return {}

        if not isinstance(section, dict):
            raise ValueError(
                f"Section {section_name!r} must be "
                "a dictionary."
            )

        result: dict[str, MetricDefinition] = {}

        for metric_name, metric_definition in (
            section.items()
        ):
            if not isinstance(
                metric_definition,
                dict,
            ):
                raise ValueError(
                    f"Metric {metric_name!r} in "
                    f"{section_name!r} must be "
                    "a dictionary."
                )

            metric = MetricDefinition.from_config(
                name=str(metric_name),
                section=section_name,
                definition=metric_definition,
            )

            if metric.enabled:
                result[metric.name] = metric

        return result

    def get_all_metrics(
        self,
    ) -> dict[str, MetricDefinition]:
        """
        Return every enabled metric in one dictionary.

        The dependency graph and engine use this combined view.
        """

        combined: dict[
            str,
            MetricDefinition,
        ] = {}

        for section in (
            self.aggregation_metrics,
            self.lookup_metrics,
            self.derived_metrics,
            self.rule_metrics,
            self.calculations,
        ):
            for metric_name, metric in section.items():
                if metric_name in combined:
                    previous_section = combined[
                        metric_name
                    ].section

                    raise ValueError(
                        f"Metric {metric_name!r} is defined "
                        f"in both {previous_section!r} and "
                        f"{metric.section!r}."
                    )

                combined[metric_name] = metric

        return combined

    def get_metric(
        self,
        metric_name: str,
    ) -> MetricDefinition:
        metrics = self.get_all_metrics()

        try:
            return metrics[metric_name]

        except KeyError as exc:
            raise KeyError(
                f"Unknown metric: {metric_name!r}."
            ) from exc

    def get_enabled_metric_names(
        self,
    ) -> list[str]:
        return list(
            self.get_all_metrics().keys()
        )


@dataclass(frozen=True)
class RoleMapping:
    """
    Role-specific population and binding configuration.

    This contains only values that vary by role, such as:

    - population filter;
    - aggregation group-by keys;
    - source and reference keys;
    - source value-column bindings;
    - role-specific filters.
    """

    role_id: str
    name: str
    enabled: bool

    population: dict[str, Any] = field(
        default_factory=dict
    )

    bindings: dict[str, Any] = field(
        default_factory=dict
    )

    parameters: dict[str, Any] = field(
        default_factory=dict
    )

    @classmethod
    def from_config(
        cls,
        *,
        role_id: str,
        definition: dict[str, Any],
    ) -> "RoleMapping":
        if not isinstance(definition, dict):
            raise ValueError(
                f"Role mapping {role_id!r} must be "
                "a dictionary."
            )

        return cls(
            role_id=str(role_id),
            name=str(
                definition.get(
                    "name",
                    role_id,
                )
            ),
            enabled=bool(
                definition.get(
                    "enabled",
                    True,
                )
            ),
            population=dict(
                definition.get(
                    "population",
                    {},
                )
            ),
            bindings=dict(
                definition.get(
                    "bindings",
                    {},
                )
            ),
            parameters=dict(
                definition.get(
                    "parameters",
                    {},
                )
            ),
        )


@dataclass(frozen=True)
class ResolvedMetricPlan:
    """
    Executable metric plan after applying a role mapping.

    At this point, role_mapping placeholders should already
    be replaced with concrete values.
    """

    library_id: str
    role_id: str
    name: str
    version: str

    parameters: dict[str, Any]
    static_reference_data: dict[str, Any]
    population: dict[str, Any]

    metrics: dict[str, MetricDefinition]

    def get_metric(
        self,
        metric_name: str,
    ) -> MetricDefinition:
        try:
            return self.metrics[metric_name]

        except KeyError as exc:
            raise KeyError(
                f"Resolved plan does not contain metric "
                f"{metric_name!r}."
            ) from exc

    def get_metric_names(
        self,
    ) -> list[str]:
        return list(self.metrics.keys())

    def get_published_metric_names(
        self,
    ) -> list[str]:
        return [
            metric.name
            for metric in self.metrics.values()
            if metric.publish
        ]
    
    def get_published_output_names(
        self,
    ) -> list[str]:
        """
        Return business-facing output names for metrics
        configured with publish: true.
        """

        return [
            metric.output_name
            for metric in self.metrics.values()
            if metric.publish
        ]    
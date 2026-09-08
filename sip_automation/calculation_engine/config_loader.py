"""
Loads and resolves calculation-engine configuration.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from sip_automation.calculation_engine.models import (
    MetricLibrary,
    ResolvedMetricPlan,
    RoleMapping,
)


class CalculationConfigError(ValueError):
    """
    Raised when calculation configuration cannot be loaded
    or resolved.
    """


class CalculationConfigLoader:
    """
    Load the generic metric library and role-specific mappings,
    then produce one fully resolved executable plan.
    """

    @staticmethod
    def load_yaml(
        path: str | Path,
    ) -> dict[str, Any]:
        resolved_path = Path(path)

        if not resolved_path.exists():
            raise CalculationConfigError(
                f"Configuration file does not exist: "
                f"{resolved_path}"
            )

        try:
            with resolved_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                loaded = yaml.safe_load(file) or {}

        except yaml.YAMLError as exc:
            raise CalculationConfigError(
                f"Invalid YAML in {resolved_path}."
            ) from exc

        if not isinstance(loaded, dict):
            raise CalculationConfigError(
                f"Configuration root in {resolved_path} "
                "must be a dictionary."
            )

        return loaded

    @classmethod
    def load_metric_library(
        cls,
        path: str | Path,
    ) -> MetricLibrary:
        return MetricLibrary.from_config(
            cls.load_yaml(path)
        )

    @classmethod
    def load_role_mapping(
        cls,
        path: str | Path,
        role_id: str,
    ) -> RoleMapping:
        config = cls.load_yaml(path)

        roles = config.get("roles", {})

        if not isinstance(roles, dict):
            raise CalculationConfigError(
                "role_mappings.yaml must contain "
                "a dictionary named 'roles'."
            )

        if role_id not in roles:
            raise CalculationConfigError(
                f"Unknown role {role_id!r}. "
                f"Available roles: {sorted(roles)}."
            )

        role = RoleMapping.from_config(
            role_id=role_id,
            definition=roles[role_id],
        )

        if not role.enabled:
            raise CalculationConfigError(
                f"Role {role_id!r} is disabled."
            )

        return role

    @classmethod
    def build_plan(
        cls,
        *,
        metric_library_path: str | Path,
        role_mapping_path: str | Path,
        role_id: str,
    ) -> ResolvedMetricPlan:
        library = cls.load_metric_library(
            metric_library_path
        )

        if not library.enabled:
            raise CalculationConfigError(
                f"Metric library {library.library_id!r} "
                "is disabled."
            )

        role_mapping = cls.load_role_mapping(
            role_mapping_path,
            role_id,
        )

        resolved_metrics = {}

        for metric_name, metric in (
            library.get_all_metrics().items()
        ):
            resolved_definition = cls._resolve(
                deepcopy(metric.definition),
                role_mapping.bindings,
                path=f"{metric.section}.{metric_name}",
            )

            # Parse again after resolution. This is necessary
            # for role-dependent enabled values.
            resolved_metric = (
                metric.__class__.from_config(
                    name=metric.name,
                    section=metric.section,
                    definition=resolved_definition,
                )
            )

            if not resolved_metric.enabled:
                continue

            resolved_metrics[metric_name] = (
                resolved_metric
            )

        return ResolvedMetricPlan(
            library_id=library.library_id,
            role_id=role_mapping.role_id,
            name=library.name,
            version=library.version,
            parameters={
                **library.parameters,
                **role_mapping.parameters,
            },
            static_reference_data=(
                deepcopy(
                    library.static_reference_data
                )
            ),
            population=deepcopy(
                role_mapping.population
            ),
            metrics=resolved_metrics,
        )

    @classmethod
    def _resolve(
        cls,
        value: Any,
        bindings: dict[str, Any],
        *,
        path: str,
    ) -> Any:
        """
        Recursively resolve every value shaped as:

            role_mapping: "actuals.group_by"

        The surrounding dictionary must contain only the
        role_mapping key.
        """

        if isinstance(value, dict):
            if "role_mapping" in value:
                if len(value) != 1:
                    raise CalculationConfigError(
                        f"Invalid role_mapping wrapper at "
                        f"{path}. A role_mapping dictionary "
                        "cannot contain additional keys."
                    )

                dotted_key = value["role_mapping"]

                if not isinstance(
                    dotted_key,
                    str,
                ) or not dotted_key.strip():
                    raise CalculationConfigError(
                        f"role_mapping at {path} must "
                        "contain a non-empty dotted string."
                    )

                return cls._lookup_binding(
                    bindings=bindings,
                    dotted_key=dotted_key,
                    config_path=path,
                )

            return {
                key: cls._resolve(
                    child_value,
                    bindings,
                    path=f"{path}.{key}",
                )
                for key, child_value
                in value.items()
            }

        if isinstance(value, list):
            return [
                cls._resolve(
                    item,
                    bindings,
                    path=f"{path}[{index}]",
                )
                for index, item
                in enumerate(value)
            ]

        return value

    @staticmethod
    def _lookup_binding(
        *,
        bindings: dict[str, Any],
        dotted_key: str,
        config_path: str,
    ) -> Any:
        current: Any = bindings

        for part in dotted_key.split("."):
            if not isinstance(current, dict):
                raise CalculationConfigError(
                    f"Role binding {dotted_key!r} "
                    f"used at {config_path} cannot be "
                    f"resolved beyond {part!r}."
                )

            if part not in current:
                raise CalculationConfigError(
                    f"Role binding {dotted_key!r} "
                    f"used at {config_path} does not "
                    f"exist. Missing part: {part!r}."
                )

            current = current[part]

        return deepcopy(current)
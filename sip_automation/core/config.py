from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sip_automation.core.exceptions import (
    ConfigurationFileNotFoundError,
    ConfigurationValidationError,
    RuntimeParameterError,
    TableConfigurationError,
)


# config.py is located at:
#
# project_root/sip_automation/core/config.py
#
# parents[0] = core
# parents[1] = sip_automation
# parents[2] = project root

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = PROJECT_ROOT / "config"


class ConfigManager:
    """
    Central configuration manager.

    Responsibilities:
    - Read YAML configuration files.
    - Cache loaded configuration.
    - Provide table, source, database, logging, and runtime settings.
    - Resolve dotted configuration values.

    It contains no processing or business-calculation logic.
    """

    def __init__(self, config_root: Path = CONFIG_ROOT) -> None:
        self.config_root = config_root
        self._cache: dict[str, dict[str, Any]] = {}

        self._application = self._load_yaml("application.yaml")
        self._validate_application_config()

    # =====================================================
    # General application configuration
    # =====================================================

    def get_application_config(self) -> dict[str, Any]:
        return deepcopy(self._application)

    def get_application_name(self) -> str:
        return str(
            self._application
            .get("application", {})
            .get("name", "SIP Automation")
        )

    def get_application_version(self) -> str:
        return str(
            self._application
            .get("application", {})
            .get("version", "0.1.0")
        )

    def get_environment(self) -> str:
        return str(
            self._application
            .get("application", {})
            .get("environment", "local")
        )

    # =====================================================
    # Pipeline configuration
    # =====================================================

    def get_raw_load_order(self) -> list[str]:
        value = (
            self._application
            .get("pipeline", {})
            .get("raw_load_order", [])
        )

        if not isinstance(value, list):
            raise ConfigurationValidationError(
                "pipeline.raw_load_order must be a list."
            )

        return [str(table_name) for table_name in value]

    def get_canonical_build_order(self) -> list[str]:
        value = (
            self._application
            .get("pipeline", {})
            .get("canonical_build_order", [])
        )

        if not isinstance(value, list):
            raise ConfigurationValidationError(
                "pipeline.canonical_build_order must be a list."
            )

        return [str(table_name) for table_name in value]

    def get_pipeline_setting(
        self,
        setting_name: str,
        default: Any = None,
    ) -> Any:
        return (
            self._application
            .get("pipeline", {})
            .get(setting_name, default)
        )

    # =====================================================
    # Logical table configuration
    # =====================================================

    def get_enabled_tables(self) -> list[str]:
        configured_tables = self._application.get("tables", {})

        return [
            table_name
            for table_name, definition in configured_tables.items()
            if definition.get("enabled", True)
        ]

    def get_table_registration(
        self,
        table_name: str,
    ) -> dict[str, Any]:
        try:
            registration = self._application["tables"][table_name]
        except KeyError as exc:
            raise TableConfigurationError(
                f"Logical table is not registered: {table_name!r}"
            ) from exc

        if not isinstance(registration, dict):
            raise TableConfigurationError(
                f"Table registration must be an object: {table_name!r}"
            )

        return deepcopy(registration)

    def get_provider(self, table_name: str) -> str:
        registration = self.get_table_registration(table_name)

        provider = registration.get("provider")

        if not provider:
            raise TableConfigurationError(
                f"No provider is configured for table {table_name!r}."
            )

        return str(provider)

    def get_table_config(self, table_name: str) -> dict[str, Any]:
        registration = self.get_table_registration(table_name)

        config_path = registration.get("configuration_file")

        if not config_path:
            raise TableConfigurationError(
                f"No configuration_file is defined for table "
                f"{table_name!r}."
            )

        table_config = self._load_yaml(str(config_path))

        configured_logical_name = (
            table_config
            .get("table", {})
            .get("logical_name")
        )

        if configured_logical_name != table_name:
            raise TableConfigurationError(
                f"Table configuration mismatch. Requested {table_name!r}, "
                f"but {config_path!r} defines "
                f"{configured_logical_name!r}."
            )

        return table_config

    def get_table_dependencies(
        self,
        table_name: str,
    ) -> list[str]:
        table_config = self.get_table_config(table_name)

        dependencies = (
            table_config
            .get("table", {})
            .get("canonical_dependencies", [])
        )

        if not isinstance(dependencies, list):
            raise TableConfigurationError(
                f"canonical_dependencies for {table_name!r} "
                f"must be a list."
            )

        return [str(dependency) for dependency in dependencies]

    # =====================================================
    # Source-provider configuration
    # =====================================================

    def get_source_config(
        self,
        provider_name: str,
    ) -> dict[str, Any]:
        return self._load_yaml(
            f"sources/{provider_name}.yaml"
        )

    def get_source_table_config(
        self,
        *,
        provider_name: str,
        table_name: str,
    ) -> dict[str, Any]:
        source_config = self.get_source_config(provider_name)

        try:
            table_config = source_config["tables"][table_name]
        except KeyError as exc:
            raise TableConfigurationError(
                f"Provider {provider_name!r} has no source configuration "
                f"for table {table_name!r}."
            ) from exc

        return deepcopy(table_config)

    # =====================================================
    # Database object configuration
    # =====================================================

    def get_database_object(
        self,
        *,
        layer: str,
        object_name: str,
    ) -> tuple[str, str]:
        """
        Return a configured PostgreSQL schema and table name.

        Examples:
            get_database_object(layer="raw", object_name="employee")
            get_database_object(layer="canonical", object_name="sales")
            get_database_object(layer="reference", object_name="fx_rate")
        """

        try:
            definition = (
                self._application["database"][layer][object_name]
            )
        except KeyError as exc:
            raise TableConfigurationError(
                f"Database object is not configured: "
                f"{layer}.{object_name}"
            ) from exc

        schema_name = definition.get("schema")
        table_name = definition.get("table")

        if not schema_name or not table_name:
            raise TableConfigurationError(
                f"Database object {layer}.{object_name} must define "
                f"both schema and table."
            )

        return str(schema_name), str(table_name)

    def resolve_database_reference(
        self,
        reference_definition: dict[str, Any],
    ) -> tuple[str, str]:
        """
        Resolve a database reference used in an enrichment definition.

        Example configuration:

            reference:
              layer: reference
              object: fx_rate
        """

        layer = reference_definition.get("layer")
        object_name = reference_definition.get("object")

        if not layer or not object_name:
            raise TableConfigurationError(
                "A database reference must define layer and object."
            )

        return self.get_database_object(
            layer=str(layer),
            object_name=str(object_name),
        )

    # =====================================================
    # Runtime defaults
    # =====================================================

    def get_runtime_defaults(self) -> dict[str, Any]:
        defaults = self._application.get(
            "runtime_defaults",
            {},
        )

        if not isinstance(defaults, dict):
            raise ConfigurationValidationError(
                "runtime_defaults must be an object."
            )

        return deepcopy(defaults)

    def get_calculation_parameters(self) -> dict[str, Any]:
        """
        Return the finance-controlled SIP calculation parameter defaults
        defined in config/calculations/sip_metrics.yaml.
        """

        config = self._load_yaml("calculations/sip_metrics.yaml")
        parameters = config.get("parameters", {})

        if not isinstance(parameters, dict):
            raise ConfigurationValidationError(
                "calculations/sip_metrics.yaml must contain a 'parameters' object."
            )

        return deepcopy(parameters)

    def get_runtime_default(
        self,
        dotted_path: str,
        default: Any = None,
        *,
        required: bool = False,
    ) -> Any:
        """
        Retrieve a runtime default by dotted path.

        Examples:
            fiscal_year
            record_source.employee
            record_source.sales
        """

        value = self._get_dotted_value(
            self.get_runtime_defaults(),
            dotted_path,
            default=default,
        )

        if required and value is None:
            raise RuntimeParameterError(
                f"Required runtime default is unavailable: "
                f"{dotted_path!r}"
            )

        return value

    # =====================================================
    # Logging configuration
    # =====================================================

    def get_logging_config(self) -> dict[str, Any]:
        config = self._load_yaml("logging.yaml")

        logging_config = config.get("logging", config)

        if not isinstance(logging_config, dict):
            raise ConfigurationValidationError(
                "logging.yaml must contain a logging object."
            )

        return logging_config

    # =====================================================
    # Internal helpers
    # =====================================================

    def _load_yaml(
        self,
        relative_path: str,
    ) -> dict[str, Any]:
        normalized_path = relative_path.replace("\\", "/")

        if normalized_path in self._cache:
            return deepcopy(self._cache[normalized_path])

        path = self.config_root / normalized_path

        if not path.exists():
            raise ConfigurationFileNotFoundError(
                f"Configuration file not found: {path}"
            )

        try:
            with path.open(
                "r",
                encoding="utf-8",
            ) as stream:
                content = yaml.safe_load(stream)
        except yaml.YAMLError as exc:
            raise ConfigurationValidationError(
                f"Invalid YAML in configuration file: {path}"
            ) from exc

        if content is None:
            content = {}

        if not isinstance(content, dict):
            raise ConfigurationValidationError(
                f"Configuration file must contain a YAML object: {path}"
            )

        self._cache[normalized_path] = content

        return deepcopy(content)

    def _validate_application_config(self) -> None:
        required_sections = {
            "application",
            "pipeline",
            "tables",
            "database",
        }

        missing_sections = sorted(
            required_sections - set(self._application)
        )

        if missing_sections:
            raise ConfigurationValidationError(
                f"application.yaml is missing sections: "
                f"{missing_sections}"
            )

        configured_tables = set(
            self._application.get("tables", {})
        )

        raw_order = set(self.get_raw_load_order())
        canonical_order = set(
            self.get_canonical_build_order()
        )

        unknown_raw_tables = sorted(
            raw_order - configured_tables
        )

        unknown_canonical_tables = sorted(
            canonical_order - configured_tables
        )

        if unknown_raw_tables:
            raise ConfigurationValidationError(
                f"raw_load_order contains unregistered tables: "
                f"{unknown_raw_tables}"
            )

        if unknown_canonical_tables:
            raise ConfigurationValidationError(
                f"canonical_build_order contains unregistered tables: "
                f"{unknown_canonical_tables}"
            )

    @staticmethod
    def _get_dotted_value(
        data: dict[str, Any],
        dotted_path: str,
        *,
        default: Any = None,
    ) -> Any:
        current: Any = data

        for part in dotted_path.split("."):
            if not isinstance(current, dict):
                return default

            if part not in current:
                return default

            current = current[part]

        return current

    def clear_cache(self) -> None:
        """
        Clear loaded YAML configuration.

        Primarily useful for automated tests or controlled configuration
        reloads. Production requests should normally use the cached config.
        """

        self._cache.clear()
        self._application = self._load_yaml(
            "application.yaml"
        )
        self._validate_application_config()


@lru_cache(maxsize=1)
def get_config_manager() -> ConfigManager:
    """
    Return one cached ConfigManager instance.
    """

    return ConfigManager()
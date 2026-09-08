from __future__ import annotations

from collections.abc import Callable

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import LoaderNotFoundError
from sip_automation.loaders.base_loader import BaseLoader
from sip_automation.loaders.excel_loader import ExcelLoader


LoaderBuilder = Callable[
    [ConfigManager],
    BaseLoader,
]


class LoaderFactory:
    """
    Create source loaders using configured provider names.

    Pipeline code requests a loader for a logical table and does not need
    to know whether the source is Excel, Workday, Snowflake, or another
    system.
    """

    def __init__(
        self,
        config: ConfigManager,
    ) -> None:
        self.config = config

        self._registry: dict[str, LoaderBuilder] = {
            "excel": ExcelLoader,
        }

        self._instances: dict[str, BaseLoader] = {}

    def create_for_table(
        self,
        logical_table_name: str,
    ) -> BaseLoader:
        provider_name = self.config.get_provider(
            logical_table_name
        )

        return self.create_for_provider(
            provider_name
        )

    def create_for_provider(
        self,
        provider_name: str,
    ) -> BaseLoader:
        normalized_name = (
            provider_name
            .strip()
            .lower()
        )

        if normalized_name in self._instances:
            return self._instances[normalized_name]

        builder = self._registry.get(
            normalized_name
        )

        if builder is None:
            raise LoaderNotFoundError(
                f"No loader implementation is registered for provider "
                f"{provider_name!r}. Registered providers: "
                f"{sorted(self._registry)}"
            )

        loader = builder(self.config)

        self._instances[normalized_name] = loader

        return loader

    def register(
        self,
        provider_name: str,
        builder: LoaderBuilder,
        *,
        replace: bool = False,
    ) -> None:
        """
        Register another provider implementation.

        Future example:

            factory.register(
                "snowflake",
                SnowflakeLoader,
            )
        """

        normalized_name = (
            provider_name
            .strip()
            .lower()
        )

        if (
            normalized_name in self._registry
            and not replace
        ):
            raise ValueError(
                f"Loader provider is already registered: "
                f"{normalized_name!r}"
            )

        self._registry[normalized_name] = builder

        if replace:
            existing_instance = self._instances.pop(
                normalized_name,
                None,
            )

            if existing_instance is not None:
                existing_instance.close()

    def registered_providers(self) -> tuple[str, ...]:
        return tuple(
            sorted(self._registry)
        )

    def close(self) -> None:
        for loader in self._instances.values():
            loader.close()

        self._instances.clear()
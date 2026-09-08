"registry.py - Registry of reusable calculation operations for the calculation engine."
from __future__ import annotations

from typing import Dict

from sip_automation.calculation_engine.operations import (
    DEFAULT_OPERATIONS,
    BaseOperation,
)


class OperationRegistry:
    """
    Registry of reusable calculation operations.

    Maps an operation name declared in YAML to the Python
    implementation responsible for executing it.
    """

    def __init__(self) -> None:

        self._operations: Dict[
            str,
            BaseOperation,
        ] = {}

        self.register_many(
            DEFAULT_OPERATIONS,
        )

    def register(
        self,
        operation: BaseOperation,
    ) -> None:

        name = operation.operation_name

        if name in self._operations:

            raise ValueError(
                f"Operation '{name}' "
                "already registered."
            )

        self._operations[name] = operation

    def register_many(
        self,
        operations,
    ) -> None:

        for operation in operations:
            self.register(operation)

    def get(
        self,
        operation_name: str,
    ) -> BaseOperation:

        try:
            return self._operations[
                operation_name
            ]

        except KeyError as exc:

            raise KeyError(
                f"Unknown operation "
                f"'{operation_name}'."
            ) from exc

    def exists(
        self,
        operation_name: str,
    ) -> bool:

        return operation_name in self._operations

    def names(
        self,
    ) -> list[str]:

        return sorted(
            self._operations.keys()
        )
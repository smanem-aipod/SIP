from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import pandas as pd

from sip_automation.core.run_context import RunContext


@dataclass(frozen=True)
class LoadResult:
    """
    Result returned by every source loader.

    The DataFrame contains source data exactly as retrieved. Mapping,
    cleaning, datatype conversion, and validation happen downstream.
    """

    logical_table_name: str
    provider_name: str
    dataframe: pd.DataFrame

    source_name: str | None = None
    source_metadata: dict[str, Any] | None = None

    @property
    def row_count(self) -> int:
        return len(self.dataframe)

    @property
    def column_count(self) -> int:
        return len(self.dataframe.columns)

    @property
    def columns(self) -> list[str]:
        return [
            str(column)
            for column in self.dataframe.columns
        ]


class BaseLoader(ABC):
    """
    Abstract interface implemented by all source loaders.

    Examples of future implementations:
    - ExcelLoader
    - WorkdayLoader
    - SnowflakeLoader
    - PostgreSQLLoader
    - CSVLoader
    """

    provider_name: str

    @abstractmethod
    def load(
        self,
        logical_table_name: str,
        context: RunContext,
    ) -> LoadResult:
        """
        Retrieve one configured logical dataset.

        The returned DataFrame must preserve source headers and source
        values. No canonical mappings or business processing should occur
        inside a loader.
        """

    def close(self) -> None:
        """
        Release provider-specific resources.

        Most loaders do not need this, but API or database loaders may
        override it later.
        """
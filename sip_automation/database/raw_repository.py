from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import Engine

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import (
    DatabaseReadError,
    RawTableWriteError,
)
from sip_automation.core.logging import get_logger
from sip_automation.database.base_repository import BaseRepository


logger = get_logger(__name__)


class RawRepository(BaseRepository):
    """
    Repository for raw.employee, raw.bp, and raw.sales.

    Physical schema and table names are resolved from configuration.
    """

    def __init__(
        self,
        engine: Engine,
        config: ConfigManager,
    ):
        super().__init__(engine)
        self.config = config

    def get_target(
        self,
        logical_table_name: str,
    ) -> tuple[str, str]:
        return self.config.get_database_object(
            layer="raw",
            object_name=logical_table_name,
        )

    def insert(
        self,
        logical_table_name: str,
        dataframe: pd.DataFrame,
        *,
        chunksize: int = 2_000,
    ) -> int:
        """
        Append records into the configured raw table.

        Identity columns such as employee_sk, bp_sk, and sales_target_sk
        must be omitted so PostgreSQL can generate them.
        """

        schema_name, table_name = self.get_target(
            logical_table_name
        )

        try:
            return self.append_dataframe(
                dataframe,
                schema_name=schema_name,
                table_name=table_name,
                chunksize=chunksize,
            )

        except Exception as exc:
            raise RawTableWriteError(
                f"Unable to write raw dataset "
                f"{logical_table_name!r} into "
                f"{schema_name}.{table_name}."
            ) from exc

    def read(
        self,
        logical_table_name: str,
        *,
        columns: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
    ) -> pd.DataFrame:
        schema_name, table_name = self.get_target(
            logical_table_name
        )

        try:
            return self.read_table(
                schema_name=schema_name,
                table_name=table_name,
                columns=columns,
                filters=filters,
                order_by=order_by,
            )

        except Exception as exc:
            raise DatabaseReadError(
                f"Unable to read raw dataset "
                f"{logical_table_name!r} from "
                f"{schema_name}.{table_name}."
            ) from exc
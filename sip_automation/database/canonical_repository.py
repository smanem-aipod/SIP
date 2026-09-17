from __future__ import annotations

from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import Engine, text

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import (
    CanonicalTableWriteError,
    DatabaseReadError,
)
from sip_automation.core.logging import get_logger
from sip_automation.database.base_repository import BaseRepository


logger = get_logger(__name__)


class CanonicalRepository(BaseRepository):
    """
    Repository for canonical.employee, canonical.bp, and canonical.sales.
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
            layer="canonical",
            object_name=logical_table_name,
        )

    def delete_by_run(
        self,
        logical_table_name: str,
        run_id: UUID | str,
    ) -> int:
        """
        Delete any existing rows for this pipeline run from a canonical
        table, so rebuilding canonical data for an already-processed run
        (e.g. after applying a Data Correction) replaces that run's rows
        instead of silently appending duplicates on top of them.
        """
        schema_name, table_name = self.get_target(
            logical_table_name
        )

        try:
            with self.engine.begin() as connection:
                result = connection.execute(
                    text(
                        f'DELETE FROM "{schema_name}"."{table_name}" '
                        f'WHERE pipeline_run_id = :run_id'
                    ),
                    {"run_id": str(run_id)},
                )
                return result.rowcount or 0

        except Exception as exc:
            raise CanonicalTableWriteError(
                f"Unable to clear existing canonical rows for "
                f"{logical_table_name!r} and run {run_id!s} from "
                f"{schema_name}.{table_name}."
            ) from exc

    def insert(
        self,
        logical_table_name: str,
        dataframe: pd.DataFrame,
        *,
        chunksize: int = 2_000,
    ) -> int:
        """
        Append a prepared, validated DataFrame to a canonical table.

        This method never creates, replaces, truncates, or alters a table.
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
            raise CanonicalTableWriteError(
                f"Unable to write canonical dataset "
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
                f"Unable to read canonical dataset "
                f"{logical_table_name!r} from "
                f"{schema_name}.{table_name}."
            ) from exc
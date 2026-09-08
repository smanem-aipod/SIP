from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
import numpy as np
import pandas as pd
from sqlalchemy import Engine, MetaData, Table, text
from sqlalchemy.exc import SQLAlchemyError

from sip_automation.core.exceptions import (
    DatabaseReadError,
    RepositoryError,
)
from sip_automation.core.logging import get_logger
from sip_automation.database.schema_inspector import (
    DatabaseSchemaInspector,
)


logger = get_logger(__name__)


_SAFE_IDENTIFIER = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*$"
)


class _CopyUnavailableError(Exception):
    """
    Raised internally when the PostgreSQL COPY fast-path cannot be used
    (e.g. the DBAPI driver does not expose a copy() cursor method).

    This is caught by append_dataframe() to trigger the chunked INSERT
    fallback; it is never raised to callers.
    """


class BaseRepository:
    """
    Shared database operations for configured PostgreSQL tables.
    """

    def __init__(self, engine: Engine):
        self.engine = engine
        self.schema_inspector = DatabaseSchemaInspector(engine)

    @staticmethod
    def validate_identifier(identifier: str) -> None:
        """
        Validate table, schema, and column names before using them in SQL.

        SQL parameters cannot be used for identifiers, so configured
        identifiers must be validated before query construction.
        """

        if not _SAFE_IDENTIFIER.fullmatch(identifier):
            raise RepositoryError(
                f"Unsafe PostgreSQL identifier: {identifier!r}"
            )

    @classmethod
    def qualified_table_name(
        cls,
        *,
        schema_name: str,
        table_name: str,
    ) -> str:
        cls.validate_identifier(schema_name)
        cls.validate_identifier(table_name)

        return f'"{schema_name}"."{table_name}"'

    def table_exists(
        self,
        *,
        schema_name: str,
        table_name: str,
    ) -> bool:
        return self.schema_inspector.table_exists(
            schema_name=schema_name,
            table_name=table_name,
        )

    def read_table(
        self,
        *,
        schema_name: str,
        table_name: str,
        columns: Sequence[str] | None = None,
        filters: Mapping[str, Any] | None = None,
        order_by: Sequence[str] | None = None,
    ) -> pd.DataFrame:
        """
        Read an existing table using optional equality filters.

        This method does not allow arbitrary SQL from configuration.
        """

        self.schema_inspector.require_table(
            schema_name=schema_name,
            table_name=table_name,
        )

        qualified_name = self.qualified_table_name(
            schema_name=schema_name,
            table_name=table_name,
        )

        if columns:
            for column in columns:
                self.validate_identifier(column)

            select_clause = ", ".join(
                f'"{column}"'
                for column in columns
            )
        else:
            select_clause = "*"

        query = f"SELECT {select_clause} FROM {qualified_name}"

        parameters: dict[str, Any] = {}

        if filters:
            clauses: list[str] = []

            for index, (column, value) in enumerate(
                filters.items()
            ):
                self.validate_identifier(column)

                parameter_name = f"filter_{index}"

                if value is None:
                    clauses.append(f'"{column}" IS NULL')
                else:
                    clauses.append(
                        f'"{column}" = :{parameter_name}'
                    )
                    parameters[parameter_name] = value

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

        if order_by:
            for column in order_by:
                self.validate_identifier(column)

            query += " ORDER BY " + ", ".join(
                f'"{column}"'
                for column in order_by
            )

        try:
            return pd.read_sql(
                text(query),
                self.engine,
                params=parameters,
            )

        except SQLAlchemyError as exc:
            logger.exception(
                "database_table_read_failed",
                schema=schema_name,
                table=table_name,
                error_type=type(exc).__name__,
            )

            raise DatabaseReadError(
                f"Unable to read PostgreSQL table "
                f"{schema_name}.{table_name}."
            ) from exc

    def count_rows(
        self,
        *,
        schema_name: str,
        table_name: str,
        filters: Mapping[str, Any] | None = None,
    ) -> int:
        frame = self.read_table(
            schema_name=schema_name,
            table_name=table_name,
            columns=None,
            filters=filters,
        )

        return len(frame)

    def append_dataframe(
        self,
        dataframe: pd.DataFrame,
        *,
        schema_name: str,
        table_name: str,
        chunksize: int = 2_000,
    ) -> int:
        """
        Append a DataFrame to an existing PostgreSQL table.

        The destination table is reflected from PostgreSQL so SQLAlchemy uses
        the table's real column datatypes when binding values.

        This method never creates, replaces, truncates, or alters the table.
        """

        if dataframe.empty:
            logger.info(
                "database_append_skipped_empty_dataframe",
                schema=schema_name,
                table=table_name,
            )
            return 0

        self.schema_inspector.require_table(
            schema_name=schema_name,
            table_name=table_name,
        )

        self.schema_inspector.validate_dataframe_columns(
            dataframe_columns=list(dataframe.columns),
            schema_name=schema_name,
            table_name=table_name,
            allow_generated_columns=False,
        )

        prepared_frame = self._prepare_for_database(dataframe)

        metadata = MetaData()

        destination_table = Table(
            table_name,
            metadata,
            schema=schema_name,
            autoload_with=self.engine,
        )

        # ---- OLD (v1): chunked INSERT executemany, ~2,000 rows per batch ----
        # records = self._dataframe_to_records(prepared_frame)
        #
        # try:
        #     with self.engine.begin() as connection:
        #         for start_index in range(0, len(records), chunksize):
        #             chunk = records[
        #                 start_index:start_index + chunksize
        #             ]
        #
        #             connection.execute(
        #                 destination_table.insert(),
        #                 chunk,
        #             )
        #
        # except (SQLAlchemyError, ValueError, TypeError) as exc:
        # ---- END OLD (v1) ----

        # ---- NEW (v2 change): PostgreSQL COPY fast path, INSERT as fallback ----
        # Bulk-load rows using PostgreSQL's native COPY protocol instead of
        # chunked INSERT statements. COPY streams rows over the wire and
        # skips per-row SQL parsing/planning, which is typically 10-50x
        # faster than executemany-style INSERTs for large DataFrames. The
        # psycopg (v3) driver already configured for this engine supports
        # COPY natively, so no new dependency is required. If COPY cannot
        # be used for any reason (e.g. a different DBAPI driver without
        # copy() support), we transparently fall back to the original
        # chunked INSERT approach (_insert_dataframe_in_chunks) so
        # behavior is preserved.
        try:  # v2 change
            try:  # v2 change
                self._copy_dataframe(  # v2 change
                    prepared_frame,
                    schema_name=schema_name,
                    table_name=table_name,
                )
            except _CopyUnavailableError:  # v2 change
                logger.info(
                    "database_copy_unavailable_falling_back_to_insert",
                    schema=schema_name,
                    table=table_name,
                )
                self._insert_dataframe_in_chunks(  # v2 change
                    prepared_frame,
                    destination_table=destination_table,
                    chunksize=chunksize,
                )
        # ---- END NEW (v2 change) ----

        except (SQLAlchemyError, ValueError, TypeError) as exc:
            logger.exception(
                "database_dataframe_append_failed",
                schema=schema_name,
                table=table_name,
                row_count=len(dataframe),
                column_count=len(dataframe.columns),
                error_type=type(exc).__name__,
            )

            raise RepositoryError(
                f"Unable to append data into "
                f"{schema_name}.{table_name}."
            ) from exc

        logger.info(
            "database_dataframe_appended",
            schema=schema_name,
            table=table_name,
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
        )

        return len(dataframe)

    # ---- v2 change: new method, did not exist in v1 ----
    def _copy_dataframe(
        self,
        dataframe: pd.DataFrame,
        *,
        schema_name: str,
        table_name: str,
    ) -> None:
        """
        Bulk-load a DataFrame using PostgreSQL COPY FROM STDIN.

        NEW (v2 change): This is the fast path for append_dataframe(). It
        streams rows directly through the psycopg (v3) driver's native
        copy() cursor method instead of building and executing INSERT
        statements, which avoids per-row SQL parsing/planning overhead
        entirely.

        Raises _CopyUnavailableError so the caller can fall back to the
        original chunked INSERT approach when COPY is not supported by the
        underlying DBAPI driver.
        """

        columns = list(dataframe.columns)

        for column in columns:
            self.validate_identifier(column)

        quoted_columns = ", ".join(
            f'"{column}"' for column in columns
        )

        qualified_name = self.qualified_table_name(
            schema_name=schema_name,
            table_name=table_name,
        )

        copy_sql = (
            f"COPY {qualified_name} ({quoted_columns}) FROM STDIN"
        )

        # Reuse the same value normalization already used by the INSERT
        # path (_to_python_value) so numpy/pandas scalar types are
        # converted to plain Python values the driver can bind correctly.
        rows = (
            tuple(
                self._to_python_value(value)
                for value in record
            )
            for record in dataframe.itertuples(
                index=False,
                name=None,
            )
        )

        raw_connection = self.engine.raw_connection()

        try:
            cursor = raw_connection.cursor()

            if not hasattr(cursor, "copy"):
                raise _CopyUnavailableError(
                    "The active DBAPI driver does not support COPY."
                )

            with cursor.copy(copy_sql) as copy:
                for row in rows:
                    copy.write_row(row)

            raw_connection.commit()

        except _CopyUnavailableError:
            raw_connection.rollback()
            raise

        except Exception:
            raw_connection.rollback()
            raise

        finally:
            raw_connection.close()

    # ---- v2 change: extracted from old (v1) append_dataframe body above, unchanged logic ----
    def _insert_dataframe_in_chunks(
        self,
        dataframe: pd.DataFrame,
        *,
        destination_table: Table,
        chunksize: int,
    ) -> None:
        """
        Original chunked INSERT logic, kept as the fallback bulk-load path
        for DBAPI drivers that do not support COPY.
        """

        records = self._dataframe_to_records(dataframe)

        with self.engine.begin() as connection:
            for start_index in range(0, len(records), chunksize):
                chunk = records[
                    start_index:start_index + chunksize
                ]

                connection.execute(
                    destination_table.insert(),
                    chunk,
                )

    @staticmethod
    def _prepare_for_database(
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Convert pandas missing values into Python None values so PostgreSQL
        receives SQL NULL rather than pandas NA/NaT objects.
        """

        result = dataframe.copy()

        return result.astype(object).where(
            pd.notna(result),
            None,
        )
    
    @classmethod
    def _dataframe_to_records(
        cls,
        dataframe: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        """
        Convert a DataFrame into database-ready record dictionaries.

        NumPy scalar values are converted into normal Python values so the
        PostgreSQL driver can bind them correctly.
        """

        records: list[dict[str, Any]] = []

        for row in dataframe.to_dict(orient="records"):
            prepared_row = {
                column: cls._to_python_value(value)
                for column, value in row.items()
            }

            records.append(prepared_row)

        return records


    @staticmethod
    def _to_python_value(value: Any) -> Any:
        """
        Convert pandas and NumPy values to PostgreSQL-compatible Python values.
        """

        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass

        if isinstance(value, np.generic):
            return value.item()

        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()

        return value    
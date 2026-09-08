from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, inspect
from sqlalchemy.exc import SQLAlchemyError

from sip_automation.core.exceptions import (
    DatabaseObjectNotFoundError,
    DatabaseReadError,
)
from sip_automation.core.logging import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class ColumnMetadata:
    name: str
    data_type: str
    nullable: bool
    default: str | None
    primary_key: bool
    autoincrement: bool | str | None


@dataclass(frozen=True)
class TableMetadata:
    schema_name: str
    table_name: str
    columns: tuple[ColumnMetadata, ...]

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(column.name for column in self.columns)

    @property
    def primary_key_columns(self) -> tuple[str, ...]:
        return tuple(
            column.name
            for column in self.columns
            if column.primary_key
        )


class DatabaseSchemaInspector:
    """
    Reads metadata for existing PostgreSQL tables.
    """

    def __init__(self, engine: Engine):
        self.engine = engine

    def table_exists(
        self,
        *,
        schema_name: str,
        table_name: str,
    ) -> bool:
        try:
            inspector = inspect(self.engine)

            return inspector.has_table(
                table_name=table_name,
                schema=schema_name,
            )

        except SQLAlchemyError as exc:
            raise DatabaseReadError(
                f"Unable to inspect table "
                f"{schema_name}.{table_name}."
            ) from exc

    def require_table(
        self,
        *,
        schema_name: str,
        table_name: str,
    ) -> None:
        if not self.table_exists(
            schema_name=schema_name,
            table_name=table_name,
        ):
            raise DatabaseObjectNotFoundError(
                f"Configured PostgreSQL table does not exist: "
                f"{schema_name}.{table_name}"
            )

    def inspect_table(
        self,
        *,
        schema_name: str,
        table_name: str,
    ) -> TableMetadata:
        self.require_table(
            schema_name=schema_name,
            table_name=table_name,
        )

        try:
            inspector = inspect(self.engine)

            raw_columns = inspector.get_columns(
                table_name=table_name,
                schema=schema_name,
            )

            primary_key_definition = inspector.get_pk_constraint(
                table_name=table_name,
                schema=schema_name,
            )

            primary_key_columns = set(
                primary_key_definition.get(
                    "constrained_columns",
                    [],
                )
                or []
            )

            columns = tuple(
                ColumnMetadata(
                    name=str(column["name"]),
                    data_type=str(column["type"]),
                    nullable=bool(column.get("nullable", True)),
                    default=(
                        None
                        if column.get("default") is None
                        else str(column["default"])
                    ),
                    primary_key=column["name"] in primary_key_columns,
                    autoincrement=column.get("autoincrement"),
                )
                for column in raw_columns
            )

            return TableMetadata(
                schema_name=schema_name,
                table_name=table_name,
                columns=columns,
            )

        except SQLAlchemyError as exc:
            raise DatabaseReadError(
                f"Unable to inspect columns for "
                f"{schema_name}.{table_name}."
            ) from exc

    def get_column_names(
        self,
        *,
        schema_name: str,
        table_name: str,
    ) -> set[str]:
        metadata = self.inspect_table(
            schema_name=schema_name,
            table_name=table_name,
        )

        return set(metadata.column_names)

    def get_insertable_columns(
        self,
        *,
        schema_name: str,
        table_name: str,
    ) -> set[str]:
        """
        Return columns that may be supplied during inserts.

        Identity or auto-incrementing primary-key fields are excluded.
        Columns with database defaults remain insertable, but callers may
        omit them and allow PostgreSQL to apply the defaults.
        """

        metadata = self.inspect_table(
            schema_name=schema_name,
            table_name=table_name,
        )

        insertable: set[str] = set()

        for column in metadata.columns:
            is_generated_primary_key = (
                column.primary_key
                and bool(column.autoincrement)
            )

            if is_generated_primary_key:
                continue

            insertable.add(column.name)

        return insertable

    def validate_dataframe_columns(
        self,
        *,
        dataframe_columns: list[str],
        schema_name: str,
        table_name: str,
        allow_generated_columns: bool = False,
    ) -> None:
        if allow_generated_columns:
            destination_columns = self.get_column_names(
                schema_name=schema_name,
                table_name=table_name,
            )
        else:
            destination_columns = self.get_insertable_columns(
                schema_name=schema_name,
                table_name=table_name,
            )

        unknown_columns = sorted(
            set(dataframe_columns) - destination_columns
        )

        if unknown_columns:
            raise DatabaseReadError(
                f"Data contains columns that do not exist or cannot be "
                f"inserted into {schema_name}.{table_name}: "
                f"{unknown_columns}"
            )

        logger.debug(
            "dataframe_columns_validated_against_database",
            schema=schema_name,
            table=table_name,
            column_count=len(dataframe_columns),
        )
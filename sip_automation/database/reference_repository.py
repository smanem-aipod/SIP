from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import Engine

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import DatabaseReadError
from sip_automation.core.logging import get_logger
from sip_automation.database.base_repository import BaseRepository


logger = get_logger(__name__)


class ReferenceRepository(BaseRepository):
    """
    Read-only repository for configured reference tables.
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
        reference_name: str,
    ) -> tuple[str, str]:
        return self.config.get_database_object(
            layer="reference",
            object_name=reference_name,
        )

    def read(
        self,
        reference_name: str,
        *,
        columns: list[str] | None = None,
        filters: dict[str, Any] | None = None,
        order_by: list[str] | None = None,
    ) -> pd.DataFrame:
        schema_name, table_name = self.get_target(
            reference_name
        )

        try:
            frame = self.read_table(
                schema_name=schema_name,
                table_name=table_name,
                columns=columns,
                filters=filters,
                order_by=order_by,
            )

        except Exception as exc:
            raise DatabaseReadError(
                f"Unable to read reference dataset "
                f"{reference_name!r} from "
                f"{schema_name}.{table_name}."
            ) from exc

        logger.info(
            "reference_dataset_loaded",
            reference_name=reference_name,
            schema=schema_name,
            table=table_name,
            row_count=len(frame),
            column_count=len(frame.columns),
        )

        return frame

    def read_fx_rates(
        self,
        *,
        fiscal_year: int | None = None,
        rate_basis: str | None = None,
        rate_value: str | None = None,
        currency_code: str | None = None,
    ) -> pd.DataFrame:
        filters: dict[str, Any] = {}

        if fiscal_year is not None:
            filters["fiscal_year"] = fiscal_year

        if rate_basis is not None:
            filters["rate_basis"] = rate_basis

        if rate_value is not None:
            filters["rate_value"] = rate_value

        if currency_code is not None:
            filters["currency_code"] = currency_code

        return self.read(
            "fx_rate",
            filters=filters or None,
        )

    def read_employee_seller_bridge(
        self,
        *,
        employee_id: str | None = None,
        seller_id: str | None = None,
        business_unit: str | None = None,
    ) -> pd.DataFrame:
        filters: dict[str, Any] = {}

        if employee_id is not None:
            filters["employee_id"] = employee_id

        if seller_id is not None:
            filters["seller_id"] = seller_id

        if business_unit is not None:
            filters["bu"] = business_unit

        return self.read(
            "employee_seller",
            filters=filters or None,
        )
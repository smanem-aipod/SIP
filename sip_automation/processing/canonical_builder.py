from __future__ import annotations

from typing import Any

import pandas as pd

from sip_automation.core.exceptions import ColumnMappingError
from sip_automation.core.logging import get_logger


logger = get_logger(__name__)


class CanonicalBuilder:
    """
    Create a canonical working DataFrame from a raw-table DataFrame.

    It copies direct fields only. Derived columns and reference joins are
    handled by Transformer and Enricher.
    """

    @classmethod
    def build(
        cls,
        raw_dataframe: pd.DataFrame,
        *,
        logical_table_name: str,
        table_config: dict[str, Any],
    ) -> pd.DataFrame:
        if not isinstance(raw_dataframe, pd.DataFrame):
            raise ColumnMappingError(
                f"Canonical builder expected a DataFrame for "
                f"{logical_table_name!r}."
            )

        raw_to_canonical = table_config.get(
            "raw_to_canonical",
        )

        if not isinstance(raw_to_canonical, dict):
            raise ColumnMappingError(
                f"Table {logical_table_name!r} does not define "
                f"raw_to_canonical."
            )

        direct_mappings = raw_to_canonical.get(
            "direct_mappings",
        )

        if not isinstance(direct_mappings, dict):
            raise ColumnMappingError(
                f"Table {logical_table_name!r} must define "
                f"raw_to_canonical.direct_mappings."
            )

        missing_raw_columns = sorted(
            set(direct_mappings.keys())
            - set(raw_dataframe.columns)
        )

        if missing_raw_columns:
            raise ColumnMappingError(
                f"Raw dataset {logical_table_name!r} is missing "
                f"columns required for canonical mapping: "
                f"{missing_raw_columns}"
            )

        canonical_frame = raw_dataframe[
            list(direct_mappings.keys())
        ].rename(
            columns=direct_mappings
        ).copy()

        duplicate_columns = canonical_frame.columns[
            canonical_frame.columns.duplicated()
        ].tolist()

        if duplicate_columns:
            raise ColumnMappingError(
                f"Canonical mapping for {logical_table_name!r} "
                f"produced duplicate columns: {duplicate_columns}"
            )

        logger.info(
            "canonical_dataframe_built",
            logical_table_name=logical_table_name,
            row_count=len(canonical_frame),
            column_count=len(canonical_frame.columns),
        )

        return canonical_frame
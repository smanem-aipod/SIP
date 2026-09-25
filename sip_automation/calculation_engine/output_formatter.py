from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


class OutputFormattingError(Exception):
    """
    Raised when an output-layout configuration is invalid or
    when the calculated DataFrame cannot be formatted.
    """


@dataclass(frozen=True)
class OutputColumn:
    """
    Definition for one final output column.

    source:
        Existing DataFrame column.

    header:
        Business-facing CSV/Excel header.
    """

    source: str
    header: str


@dataclass(frozen=True)
class OutputLayout:
    """
    Parsed final-output layout.
    """

    name: str
    missing_column_policy: str
    columns: tuple[OutputColumn, ...]


class SIPOutputFormatter:
    """
    Format SIP calculation results into the exact finance-facing
    column order and header structure defined in YAML.

    The formatter:

        1. reads the configured ordered column list;
        2. retrieves each source column;
        3. optionally creates missing columns as null;
        4. applies business-facing headers;
        5. returns only the configured columns.

    The implementation builds each output column independently.
    This allows duplicate final headers, such as:

        Region Currency
        ...
        Region Currency

    when Finance requires that exact workbook structure.
    """

    VALID_MISSING_COLUMN_POLICIES = {
        "error",
        "add_null",
        "skip",
    }

    @classmethod
    def from_yaml(
        cls,
        layout_path: str | Path,
        *,
        quarter: str | None = None,
    ) -> OutputLayout:
        """
        Load and validate an output-layout YAML file.
        """

        resolved_path = Path(layout_path).resolve()

        if not resolved_path.exists():
            raise OutputFormattingError(
                f"Output-layout file does not exist: "
                f"{resolved_path}"
            )

        if not resolved_path.is_file():
            raise OutputFormattingError(
                f"Output-layout path is not a file: "
                f"{resolved_path}"
            )

        try:
            with resolved_path.open(
                "r",
                encoding="utf-8",
            ) as file:
                config = yaml.safe_load(file) or {}

        except yaml.YAMLError as exc:
            raise OutputFormattingError(
                f"Unable to parse output-layout YAML: "
                f"{resolved_path}"
            ) from exc

        output_config = config.get("output")

        if not isinstance(output_config, dict):
            raise OutputFormattingError(
                "Output-layout YAML must contain an "
                "'output' dictionary."
            )

        name = str(
            output_config.get(
                "name",
                "sip_output",
            )
        ).strip()

        missing_column_policy = str(
            output_config.get(
                "missing_column_policy",
                "error",
            )
        ).strip().lower()

        if (
            missing_column_policy
            not in cls.VALID_MISSING_COLUMN_POLICIES
        ):
            raise OutputFormattingError(
                "Unsupported missing_column_policy "
                f"{missing_column_policy!r}. Expected one of: "
                f"{sorted(cls.VALID_MISSING_COLUMN_POLICIES)}."
            )

        configured_columns = output_config.get("columns")

        if not isinstance(configured_columns, list):
            raise OutputFormattingError(
                "output.columns must be a list."
            )

        if not configured_columns:
            raise OutputFormattingError(
                "output.columns cannot be empty."
            )

        parsed_columns: list[OutputColumn] = []

        for index, column_config in enumerate(
            configured_columns,
            start=1,
        ):
            if not isinstance(column_config, dict):
                raise OutputFormattingError(
                    f"Output column #{index} must be a dictionary."
                )

            source = column_config.get("source")
            header = column_config.get("header")

            if not isinstance(source, str) or not source.strip():
                raise OutputFormattingError(
                    f"Output column #{index} must define a "
                    "non-empty string 'source'."
                )

            source = source.strip()

            if header is None:
                header = source

            if not isinstance(header, str) or not header.strip():
                raise OutputFormattingError(
                    f"Output column #{index} must define a "
                    "non-empty string 'header'."
                )

            header = header.strip()

            # Mirrors MetricDefinition's output_name templating - lets a
            # column that dynamically renames itself per quarter (e.g.
            # "Guarantee SIP ({quarter})") still be found and re-labeled
            # correctly in the exported CSV.
            if quarter:
                if "{quarter}" in source:
                    source = source.format(quarter=quarter)

                if "{quarter}" in header:
                    header = header.format(quarter=quarter)

            parsed_columns.append(
                OutputColumn(
                    source=source,
                    header=header,
                )
            )

        return OutputLayout(
            name=name,
            missing_column_policy=missing_column_policy,
            columns=tuple(parsed_columns),
        )

    @classmethod
    def format(
        cls,
        dataframe: pd.DataFrame,
        *,
        layout_path: str | Path,
        quarter: str | None = None,
    ) -> pd.DataFrame:
        """
        Apply the configured order and business-facing headers.
        """

        if not isinstance(dataframe, pd.DataFrame):
            raise OutputFormattingError(
                "SIP output formatting requires a pandas DataFrame."
            )

        layout = cls.from_yaml(layout_path, quarter=quarter)

        output_series: list[pd.Series] = []
        output_headers: list[str] = []

        missing_columns: list[str] = []

        for column in layout.columns:
            if column.source in dataframe.columns:
                series = dataframe[column.source].copy()

            else:
                missing_columns.append(column.source)

                if layout.missing_column_policy == "error":
                    continue

                if layout.missing_column_policy == "skip":
                    continue

                series = pd.Series(
                    pd.NA,
                    index=dataframe.index,
                    dtype="object",
                )

            series.name = column.header

            output_series.append(series)
            output_headers.append(column.header)

        if (
            missing_columns
            and layout.missing_column_policy == "error"
        ):
            raise OutputFormattingError(
                "The following configured SIP output columns "
                "do not exist in the calculation DataFrame: "
                f"{sorted(set(missing_columns))}"
            )

        if not output_series:
            return pd.DataFrame(
                index=dataframe.index
            )

        formatted = pd.concat(
            output_series,
            axis=1,
        )

        # Explicitly assign configured headers because duplicate
        # business headers are allowed.
        formatted.columns = output_headers

        return formatted.reset_index(
            drop=True
        )

    @classmethod
    def inspect_missing_columns(
        cls,
        dataframe: pd.DataFrame,
        *,
        layout_path: str | Path,
    ) -> list[str]:
        """
        Return configured source columns that are absent from the
        supplied DataFrame.

        Useful during development before changing the policy from
        add_null to error.
        """

        layout = cls.from_yaml(layout_path)

        return [
            column.source
            for column in layout.columns
            if column.source not in dataframe.columns
        ]
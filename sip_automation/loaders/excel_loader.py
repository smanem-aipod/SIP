from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import (
    LoaderError,
    SourceFileNotFoundError,
    SourceNotConfiguredError,
    SourceTableNotFoundError,
)
from sip_automation.core.logging import get_logger
from sip_automation.core.run_context import RunContext
from sip_automation.loaders.base_loader import BaseLoader, LoadResult


logger = get_logger(__name__)


class ExcelLoader(BaseLoader):
    """
    Load configured worksheets from Excel workbooks.

    This class performs source retrieval only. It does not rename headers,
    clean values, validate data, or write to PostgreSQL.
    """

    provider_name = "excel"

    def __init__(
        self,
        config: ConfigManager,
    ) -> None:
        self.config = config
        self.source_config = config.get_source_config(
            self.provider_name
        )

    def load(
        self,
        logical_table_name: str,
        context: RunContext,
    ) -> LoadResult:
        table_source = self._get_table_source_config(
            logical_table_name
        )

        workbook_key = self._get_required_string(
            table_source,
            "workbook",
            logical_table_name=logical_table_name,
        )

        workbook_config = self._get_workbook_config(
            table_source
        )

        uploaded_file_path = None

        if context.uploaded_files is not None:
            uploaded_file_path = context.uploaded_files.get_file(
                logical_table_name
            )

        workbook_path = (
            uploaded_file_path
            if uploaded_file_path is not None
            else self._resolve_workbook_path(
                workbook_config
            )
        )

        if uploaded_file_path is not None:
            # Each UI upload represents one logical table.
            # Read the first worksheet from the uploaded file.
            sheet_name: str | int = 0

            # ---- OLD (v1): let pandas auto-pick engine by extension ----
            # engine = None
            # ---- END OLD (v1) ----

            # ---- NEW (v2 change): force python-calamine engine ----
            # Use python-calamine (Rust-based) instead of pandas' default
            # per-extension engine (openpyxl for .xlsx, pyxlsb for .xlsb).
            # Benchmarked ~6x faster on a real 152k-row/52-col sales upload
            # (174s -> 17-29s), which was the dominant cost of "uploading"
            # through the UI. Verified compatible with the same na_values/
            # keep_default_na read_options used below.
            engine = "calamine"  # v2 change
            # ---- END NEW (v2 change) ----
        else:
            sheet_name = self._get_required_string(
                table_source,
                "sheet_name",
                logical_table_name=logical_table_name,
            )

            engine = workbook_config.get("engine")

        header = table_source.get("header", 0)

        read_options = self._build_read_options(
            table_source=table_source,
            workbook_config=workbook_config,
        )

        self._validate_workbook_exists(workbook_path)

        logger.info(
            "excel_load_started",
            run_id=str(context.run_id),
            logical_table_name=logical_table_name,
            provider=self.provider_name,         
            workbook=str(workbook_path),
            workbook_key=workbook_key,
            workbook_source=(
                "uploaded"
                if uploaded_file_path is not None
                else "configured"
            ),
            sheet_name=sheet_name,
            header=header,
            engine=engine,
        )

        try:
            if uploaded_file_path is None:
                self._validate_sheet_exists(
                    workbook_path=workbook_path,
                    sheet_name=sheet_name,
                    engine=engine,
                )
            
            read_arguments = {
                "io": workbook_path,
                "sheet_name": sheet_name,
                "header": header,
                "engine": engine,
                **read_options,
            }

            if table_source.get("nrows") is not None:
                read_arguments["nrows"] = int(
                    table_source["nrows"]
                )

            dataframe = pd.read_excel(**read_arguments)

        except SourceTableNotFoundError:
            raise

        # Broad on purpose: a corrupted or non-Excel file (e.g. a text
        # file renamed to .xlsx) can fail inside whichever engine pandas
        # picked (calamine, openpyxl, xlrd, pyxlsb) with an
        # engine-specific exception type that isn't a ValueError/
        # ImportError/OSError - e.g. python_calamine.CalamineError. Any
        # failure here means "this isn't readable as Excel", so it's
        # always a LoaderError (surfaced as a friendly 422), never a
        # bare 500.
        except Exception as exc:
            logger.exception(
                "excel_load_failed",
                run_id=str(context.run_id),
                logical_table_name=logical_table_name,
                workbook=str(workbook_path),
                sheet_name=sheet_name,
                error_type=type(exc).__name__,
            )

            raise LoaderError(
                f"Unable to read Excel source for logical table "
                f"{logical_table_name!r} from workbook "
                f"{workbook_path!s}, sheet {sheet_name!r}."
            ) from exc

        if not isinstance(dataframe, pd.DataFrame):
            raise LoaderError(
                f"Excel loader did not return a DataFrame for "
                f"{logical_table_name!r}."
            )

        logger.info(
            "excel_load_completed",
            run_id=str(context.run_id),
            logical_table_name=logical_table_name,
            provider=self.provider_name,
            workbook=str(workbook_path),
            sheet_name=sheet_name,
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
        )

        return LoadResult(
            logical_table_name=logical_table_name,
            provider_name=self.provider_name,
            dataframe=dataframe,
            source_name=f"{workbook_path.name}:{sheet_name}",
            source_metadata={
                "workbook_path": str(workbook_path),
                "workbook_name": workbook_path.name,
                "workbook_key": workbook_key,
                "workbook_source": (
                    "uploaded"
                    if uploaded_file_path is not None
                    else "configured"
                ),    
                "sheet_name": sheet_name,
                "header": header,
                "engine": engine,
            },
        )

    def _get_table_source_config(
        self,
        logical_table_name: str,
    ) -> dict[str, Any]:
        tables = self.source_config.get("tables", {})

        table_source = tables.get(logical_table_name)

        if not isinstance(table_source, dict):
            raise SourceNotConfiguredError(
                f"Excel source is not configured for logical table "
                f"{logical_table_name!r}."
            )

        return table_source

    def _get_workbook_config(
        self,
        table_source: dict[str, Any],
    ) -> dict[str, Any]:
        workbook_key = table_source.get("workbook")

        if not workbook_key:
            raise SourceNotConfiguredError(
                "Excel table configuration must define a workbook."
            )

        workbooks = self.source_config.get(
            "workbooks",
            {},
        )

        workbook_config = workbooks.get(workbook_key)

        if not isinstance(workbook_config, dict):
            raise SourceNotConfiguredError(
                f"Excel workbook configuration does not exist: "
                f"{workbook_key!r}."
            )

        return workbook_config

    def _resolve_workbook_path(
        self,
        workbook_config: dict[str, Any],
    ) -> Path:
        configured_path = workbook_config.get("path")

        if not configured_path:
            raise SourceNotConfiguredError(
                "Excel workbook configuration must define a path."
            )

        workbook_path = Path(
            str(configured_path)
        ).expanduser()

        if not workbook_path.is_absolute():
            workbook_path = (
                self.config.config_root.parent
                / workbook_path
            )

        return workbook_path.resolve()

    @staticmethod
    def _validate_workbook_exists(
        workbook_path: Path,
    ) -> None:
        if not workbook_path.exists():
            raise SourceFileNotFoundError(
                f"Configured Excel workbook does not exist: "
                f"{workbook_path}"
            )

        if not workbook_path.is_file():
            raise SourceFileNotFoundError(
                f"Configured Excel path is not a file: "
                f"{workbook_path}"
            )

    @staticmethod
    def _validate_sheet_exists(
        *,
        workbook_path: Path,
        sheet_name: str | int,
        engine: str | None,
    ) -> None:
        try:
            with pd.ExcelFile(
                workbook_path,
                engine=engine,
            ) as workbook:
                available_sheets = workbook.sheet_names

        # Broad on purpose - see the matching comment above; any failure
        # to open/inspect the workbook (regardless of engine-specific
        # exception type) means this isn't a readable Excel file.
        except Exception as exc:
            raise LoaderError(
                f"Unable to inspect workbook sheets: "
                f"{workbook_path}"
            ) from exc

        if sheet_name not in available_sheets:
            raise SourceTableNotFoundError(
                f"Worksheet {sheet_name!r} does not exist in "
                f"{workbook_path.name!r}. Available worksheets: "
                f"{available_sheets}"
            )

    def _build_read_options(
        self,
        *,
        table_source: dict[str, Any],
        workbook_config: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Merge provider-wide, workbook-level, and table-level read options.

        Precedence:
            provider read_options
            < workbook read_options
            < table read_options
        """

        options: dict[str, Any] = {}

        provider_options = self.source_config.get(
            "read_options",
            {},
        )

        workbook_options = workbook_config.get(
            "read_options",
            {},
        )

        table_options = table_source.get(
            "read_options",
            {},
        )

        for configured_options in (
            provider_options,
            workbook_options,
            table_options,
        ):
            if configured_options:
                if not isinstance(configured_options, dict):
                    raise SourceNotConfiguredError(
                        "Excel read_options must be a YAML object."
                    )

                options.update(configured_options)

        reserved_arguments = {
            "io",
            "sheet_name",
            "header",
            "engine",
            "nrows",
        }

        conflicting_arguments = (
            reserved_arguments
            & set(options)
        )

        if conflicting_arguments:
            raise SourceNotConfiguredError(
                f"Excel read_options must not redefine reserved "
                f"arguments: {sorted(conflicting_arguments)}"
            )

        return options

    @staticmethod
    def _get_required_string(
        configuration: dict[str, Any],
        key: str,
        *,
        logical_table_name: str,
    ) -> str:
        value = configuration.get(key)

        if not isinstance(value, str) or not value:
            raise SourceNotConfiguredError(
                f"Excel source for {logical_table_name!r} must define "
                f"a non-empty {key!r}."
            )

        return value
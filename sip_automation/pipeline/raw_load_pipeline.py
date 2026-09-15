from __future__ import annotations

from typing import Any

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import PipelineExecutionError
from sip_automation.core.logging import get_logger
from sip_automation.core.run_context import RunContext
from sip_automation.database.raw_repository import RawRepository
from sip_automation.loaders.loader_factory import LoaderFactory
from sip_automation.pipeline.models import RawTableResult
from sip_automation.processing.datatype_converter import DataTypeConverter
from sip_automation.processing.preprocessing import DataPreprocessor
from sip_automation.processing.source_mapper import SourceMapper


logger = get_logger(__name__)


class RawLoadPipeline:
    """
    Load source datasets and publish them into the configured raw tables.

    Responsibilities:
    1. Select the configured source loader.
    2. Retrieve the source DataFrame.
    3. Map source headers to raw database columns.
    4. Perform only the conversion needed by the typed raw table.
    5. Append records to the existing raw PostgreSQL table.

    This pipeline does not create canonical fields, perform enrichments,
    or calculate business outputs.
    """

    def __init__(
        self,
        *,
        config: ConfigManager,
        loader_factory: LoaderFactory,
        raw_repository: RawRepository,
        datatype_converter: DataTypeConverter | None = None,
    ) -> None:
        self.config = config
        self.loader_factory = loader_factory
        self.raw_repository = raw_repository
        self.datatype_converter = (
            datatype_converter or DataTypeConverter()
        )

    def run(
        self,
        *,
        context: RunContext,
    ) -> dict[str, RawTableResult]:
        results: dict[str, RawTableResult] = {}

        uploaded_files = context.uploaded_files

        for logical_table_name in (
            self.config.get_raw_load_order()
        ):
            if (
                uploaded_files is not None
                and not uploaded_files.is_empty
                and uploaded_files.get_file(logical_table_name) is None
            ):
                logger.info(
                    "raw_load_pipeline_skipped",
                    run_id=str(context.run_id),
                    logical_table_name=logical_table_name,
                    reason="not_uploaded",
                )
                continue

            results[logical_table_name] = self.run_table(
                logical_table_name=logical_table_name,
                context=context,
            )

        return results

    def run_table(
        self,
        *,
        logical_table_name: str,
        context: RunContext,
    ) -> RawTableResult:
        provider_name = self.config.get_provider(
            logical_table_name
        )

        table_config = self.config.get_table_config(
            logical_table_name
        )

        loader = self.loader_factory.create_for_table(
            logical_table_name
        )

        logger.info(
            "raw_load_pipeline_started",
            run_id=str(context.run_id),
            logical_table_name=logical_table_name,
            provider=provider_name,
        )

        try:
            load_result = loader.load(
                logical_table_name,
                context,
            )

            raw_frame = SourceMapper.map_to_raw(
                load_result.dataframe,
                logical_table_name=logical_table_name,
                table_config=table_config,
                context=context,
            )

            raw_frame = self._prepare_raw_values(
                raw_frame,
                logical_table_name=logical_table_name,
                table_config=table_config,
            )

            inserted_row_count = self.raw_repository.insert(
                logical_table_name,
                raw_frame,
            )

            schema_name, table_name = (
                self.raw_repository.get_target(
                    logical_table_name
                )
            )

        except Exception as exc:
            logger.exception(
                "raw_load_pipeline_failed",
                run_id=str(context.run_id),
                logical_table_name=logical_table_name,
                provider=provider_name,
                error_type=type(exc).__name__,
            )

            raise PipelineExecutionError(
                f"Raw loading failed for logical table "
                f"{logical_table_name!r}."
            ) from exc

        logger.info(
            "raw_load_pipeline_completed",
            run_id=str(context.run_id),
            logical_table_name=logical_table_name,
            provider=provider_name,
            source_row_count=load_result.row_count,
            inserted_row_count=inserted_row_count,
            column_count=len(raw_frame.columns),
            schema=schema_name,
            table=table_name,
        )

        return RawTableResult(
            logical_table_name=logical_table_name,
            provider_name=provider_name,
            source_name=load_result.source_name,
            source_row_count=load_result.row_count,
            raw_row_count=inserted_row_count,
            raw_column_count=len(raw_frame.columns),
            schema_name=schema_name,
            table_name=table_name,
        )

    def _prepare_raw_values(
        self,
        raw_frame,
        *,
        logical_table_name: str,
        table_config: dict[str, Any],
    ):
        """
        Convert source values only where the raw PostgreSQL table requires
        typed values.

        The existing table configuration defines canonical datatypes.
        Raw columns with the same stable internal name reuse those type
        definitions.

        Example:
            raw column sip_target_pct
            canonical column sip_target_pct
            configured type percentage

        Values such as "40%" are converted to Decimal("0.4000") before
        insertion into raw.employee.sip_target_pct.
        """

        result = raw_frame.copy()

        cleaning_config = table_config.get(
            "cleaning",
            {},
        )

        raw_cleaning_config = {
            "remove_fully_empty_rows": True,
            "trim_strings": cleaning_config.get(
                "trim_strings",
                True,
            ),
            "collapse_internal_whitespace": (
                cleaning_config.get(
                    "collapse_internal_whitespace",
                    True,
                )
            ),
            "normalize_unicode": True,
            "normalize_empty_strings": (
                cleaning_config.get(
                    "normalize_empty_strings",
                    True,
                )
            ),
            "null_markers": cleaning_config.get(
                "null_markers",
                [
                    "",
                    "#N/A",
                    "N/A",
                    "NA",
                    "null",
                    "None",
                    "-",
                ],
            ),
        }

        result = DataPreprocessor.preprocess(
            result,
            logical_table_name=logical_table_name,
            cleaning_config=raw_cleaning_config,
        )

        canonical_column_config = table_config.get(
            "columns",
            {},
        )

        raw_conversion_config = {
            column_name: definition
            for column_name, definition
            in canonical_column_config.items()
            if column_name in result.columns
        }

        result = self.datatype_converter.convert(
            result,
            logical_table_name=logical_table_name,
            column_config=raw_conversion_config,
        )

        return result
from __future__ import annotations

from typing import Any

import pandas as pd

from sip_automation.core.data_corrections import (
    DataCorrectionsStore,
    apply_corrections_to_dataframe,
)
from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import (
    DataValidationError,
    PipelineExecutionError,
)
from sip_automation.core.logging import get_logger
from sip_automation.core.run_context import RunContext
from sip_automation.database.canonical_repository import (
    CanonicalRepository,
)
from sip_automation.database.raw_repository import RawRepository
from sip_automation.pipeline.models import CanonicalTableResult
from sip_automation.processing.canonical_builder import (
    CanonicalBuilder,
)
from sip_automation.processing.datatype_converter import (
    DataTypeConverter,
)
from sip_automation.processing.enricher import EnrichmentEngine
from sip_automation.processing.preprocessing import (
    DataPreprocessor,
)
from sip_automation.processing.transformer import (
    TransformationEngine,
)
from sip_automation.processing.validator import (
    TableValidator,
    ValidationReport,
)


logger = get_logger(__name__)


class CanonicalPipeline:
    """
    Build validated, typed and enriched canonical tables from raw tables.

    The canonical pipeline never reads Excel or any other source directly.
    It reads only the raw PostgreSQL layer for the active pipeline run.
    """

    def __init__(
        self,
        *,
        config: ConfigManager,
        raw_repository: RawRepository,
        canonical_repository: CanonicalRepository,
        transformation_engine: TransformationEngine,
        enrichment_engine: EnrichmentEngine,
        datatype_converter: DataTypeConverter | None = None,
    ) -> None:
        self.config = config
        self.raw_repository = raw_repository
        self.canonical_repository = canonical_repository
        self.transformation_engine = transformation_engine
        self.enrichment_engine = enrichment_engine
        self.datatype_converter = (
            datatype_converter or DataTypeConverter()
        )

    def run(
        self,
        *,
        context: RunContext,
    ) -> dict[str, CanonicalTableResult]:
        results: dict[str, CanonicalTableResult] = {}

        self._validate_configured_order()

        for logical_table_name in (
            self.config.get_canonical_build_order()
        ):
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
    ) -> CanonicalTableResult:
        logger.info(
            "canonical_pipeline_started",
            run_id=str(context.run_id),
            logical_table_name=logical_table_name,
        )

        try:
            table_config = self.config.get_table_config(
                logical_table_name
            )
            table_context = context.with_parameters(
                table_config.get(
                    "parameters",
                    {},
                )
            )
            raw_frame = self.raw_repository.read(
                logical_table_name,
                filters={
                    "pipeline_run_id": context.run_id,
                },
            )
            raw_frame = apply_corrections_to_dataframe(
                raw_frame,
                DataCorrectionsStore(
                    path=self.config.config_root.parent / "data" / "data_corrections.yaml"
                ).list(),
                logical_table_name,
            )

            if raw_frame.empty:
                logger.info(
                    "canonical_pipeline_skipped",
                    run_id=str(context.run_id),
                    logical_table_name=logical_table_name,
                    reason="no_raw_records",
                )
                schema_name, table_name = (
                    self.canonical_repository.get_target(
                        logical_table_name
                    )
                )
                empty_report = ValidationReport(
                    logical_table_name=logical_table_name,
                    issues=[],
                )
                return CanonicalTableResult(
                    logical_table_name=logical_table_name,
                    source_row_count=0,
                    canonical_row_count=0,
                    canonical_column_count=0,
                    schema_name=schema_name,
                    table_name=table_name,
                    pre_enrichment_validation=empty_report,
                    final_validation=empty_report,
                )

            canonical_frame = CanonicalBuilder.build(
                raw_frame,
                logical_table_name=logical_table_name,
                table_config=table_config,
            )
            canonical_frame = self._normalize_canonical_values(
                canonical_frame
            )

            if "pipeline_run_id" not in raw_frame.columns:
                raise PipelineExecutionError(
                    f"Raw table {logical_table_name!r} does not contain "
                    f"'pipeline_run_id'."
                )

            canonical_frame["pipeline_run_id"] = (
                raw_frame["pipeline_run_id"]
                .reset_index(drop=True)
            )

            canonical_frame = (
                DataPreprocessor.preprocess(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    cleaning_config=table_config.get(
                        "cleaning"
                    ),
                )
            )

            canonical_frame = (
                self.datatype_converter.convert(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    column_config=table_config.get(
                        "columns",
                        {},
                    ),
                )
            )

            pre_enrichment_report = (
                TableValidator.validate(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    column_config=table_config.get(
                        "columns",
                        {},
                    ),
                    validation_config=table_config.get(
                        "validations"
                    ),
                )
            )

            self._enforce_validation_policy(
                pre_enrichment_report,
                logical_table_name=logical_table_name,
                stage="pre_enrichment",
            )

            canonical_frame = (
                self.transformation_engine.apply_stage(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    derived_columns=table_config.get(
                        "derived_columns"
                    ),
                    stage="before_enrichment",
                    context=table_context,
                )
            )

            canonical_frame = (
                self.enrichment_engine.enrich(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    enrichments=table_config.get(
                        "lookups"
                    ),
                    context=table_context,
                )
            )

            canonical_frame = (
                self.transformation_engine.apply_stage(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    derived_columns=table_config.get(
                        "derived_columns"
                    ),
                    stage="after_enrichment",
                    context=table_context,
                )
            )

            canonical_frame = self._populate_unresolved_columns(
                canonical_frame,
                table_config=table_config,
                logical_table_name=logical_table_name,
            )

            canonical_frame = (
                self.datatype_converter.convert(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    column_config=table_config.get(
                        "columns",
                        {},
                    ),
                )
            )

            final_validation_report = (
                TableValidator.validate(
                    canonical_frame,
                    logical_table_name=logical_table_name,
                    column_config=table_config.get(
                        "columns",
                        {},
                    ),
                    validation_config=table_config.get(
                        "validations"
                    ),
                )
            )

            self._enforce_validation_policy(
                final_validation_report,
                logical_table_name=logical_table_name,
                stage="final",
            )

            canonical_frame = self._prepare_for_publish(
                canonical_frame,
                table_config=table_config,
                logical_table_name=logical_table_name,
            )

            # Rebuilding canonical data for an already-processed run (e.g.
            # after applying a Data Correction) must replace that run's
            # rows, not append duplicates on top of them - duplicates cause
            # lookup metrics keyed on employee_id to fail downstream.
            self.canonical_repository.delete_by_run(
                logical_table_name,
                context.run_id,
            )

            inserted_row_count = (
                self.canonical_repository.insert(
                    logical_table_name,
                    canonical_frame,
                )
            )

            schema_name, table_name = (
                self.canonical_repository.get_target(
                    logical_table_name
                )
            )

        except Exception as exc:
            logger.exception(
                "canonical_pipeline_failed",
                run_id=str(context.run_id),
                logical_table_name=logical_table_name,
                error_type=type(exc).__name__,
            )

            if isinstance(
                exc,
                (
                    PipelineExecutionError,
                    DataValidationError,
                ),
            ):
                raise

            raise PipelineExecutionError(
                f"Canonical preparation failed for "
                f"{logical_table_name!r}."
            ) from exc

        logger.info(
            "canonical_pipeline_completed",
            run_id=str(context.run_id),
            logical_table_name=logical_table_name,
            source_row_count=len(raw_frame),
            inserted_row_count=inserted_row_count,
            canonical_column_count=len(
                canonical_frame.columns
            ),
            schema=schema_name,
            table=table_name,
        )

        return CanonicalTableResult(
            logical_table_name=logical_table_name,
            source_row_count=len(raw_frame),
            canonical_row_count=inserted_row_count,
            canonical_column_count=len(
                canonical_frame.columns
            ),
            schema_name=schema_name,
            table_name=table_name,
            pre_enrichment_validation=(
                pre_enrichment_report
            ),
            final_validation=final_validation_report,
        )

    def _validate_configured_order(self) -> None:
        """
        Confirm that configured canonical dependencies appear before the
        dependent table in canonical_build_order.

        This is deliberately simpler than the future calculation-engine
        DAG. It validates the current configured order without adding a
        graph framework prematurely.
        """

        build_order = (
            self.config.get_canonical_build_order()
        )

        positions = {
            table_name: index
            for index, table_name in enumerate(
                build_order
            )
        }

        errors: list[str] = []

        for table_name in build_order:
            dependencies = (
                self.config.get_table_dependencies(
                    table_name
                )
            )

            for dependency in dependencies:
                if dependency not in positions:
                    errors.append(
                        f"{table_name!r} depends on "
                        f"unconfigured table {dependency!r}"
                    )
                    continue

                if positions[dependency] > positions[table_name]:
                    errors.append(
                        f"{table_name!r} depends on "
                        f"{dependency!r}, but {dependency!r} "
                        f"appears later in canonical_build_order"
                    )

        if errors:
            raise PipelineExecutionError(
                "Invalid canonical build order: "
                + "; ".join(errors)
            )

    def _enforce_validation_policy(
        self,
        report: ValidationReport,
        *,
        logical_table_name: str,
        stage: str,
    ) -> None:
        stop_on_error = bool(
            self.config.get_pipeline_setting(
                "stop_on_validation_error",
                True,
            )
        )

        if report.is_valid or not stop_on_error:
            return

        error_messages = [
            issue.message
            for issue in report.issues
            if issue.severity.upper() == "ERROR"
        ]

        raise DataValidationError(
            f"Validation failed for "
            f"{logical_table_name!r} during {stage}: "
            f"{error_messages}"
        )

    @staticmethod
    def _normalize_canonical_values(
        dataframe: pd.DataFrame,
    ) -> pd.DataFrame:
        result = dataframe.copy()

        for column_name in [
            "division_node",
            "ship_to",
            "material",
            "seller_id",
            "employee_id",
            "employee_id_only_for_shared",
            "cam_id",
            "bdm_id",
        ]:
            if column_name in result.columns:
                result[column_name] = (
                    result[column_name]
                    .astype("string")
                    .str.replace(
                        r"\.0$",
                        "",
                        regex=True,
                    )
                )

        for column_name in [
            "sales_group_description",
            "sales_office_description",
        ]:
            if column_name in result.columns:
                result[column_name] = (
                    result[column_name]
                    .astype("string")
                    .str.strip()
                    .str.lower()
                )

        return result

    @staticmethod
    def _populate_unresolved_columns(
        dataframe: pd.DataFrame,
        *,
        table_config: dict[str, Any],
        logical_table_name: str,
    ) -> pd.DataFrame:
        """
        Populate explicitly unresolved canonical fields with their configured
        placeholder, normally NULL.

        This prevents accidental invention of business logic while allowing
        nullable canonical columns to be published.
        """

        result = dataframe.copy()

        unresolved_columns = table_config.get(
            "unresolved_columns",
            {},
        )

        if not unresolved_columns:
            return result

        if not isinstance(unresolved_columns, dict):
            raise PipelineExecutionError(
                f"unresolved_columns for "
                f"{logical_table_name!r} must be an object."
            )

        for column_name, definition in (
            unresolved_columns.items()
        ):
            if not isinstance(definition, dict):
                raise PipelineExecutionError(
                    f"Unresolved column definition for "
                    f"{column_name!r} must be an object."
                )

            result[column_name] = definition.get(
                "populate_with"
            )

            logger.warning(
                "canonical_column_unresolved",
                logical_table_name=logical_table_name,
                column_name=column_name,
                severity=definition.get(
                    "severity",
                    "warning",
                ),
                reason=definition.get("reason"),
            )

        return result

    @staticmethod
    def _prepare_for_publish(
        dataframe: pd.DataFrame,
        *,
        table_config: dict[str, Any],
        logical_table_name: str,
    ) -> pd.DataFrame:
        publish_config = table_config.get(
            "publish",
            {},
        )

        publish_columns = publish_config.get(
            "columns"
        )

        if not isinstance(publish_columns, list):
            raise PipelineExecutionError(
                f"Table {logical_table_name!r} must define "
                f"publish.columns as a list."
            )

        missing_columns = sorted(
            set(publish_columns)
            - set(dataframe.columns)
        )

        if missing_columns:
            raise PipelineExecutionError(
                f"Canonical table {logical_table_name!r} "
                f"cannot publish missing columns: "
                f"{missing_columns}"
            )

        operational_columns = [
            "pipeline_run_id",
        ]

        missing_operational_columns = [
            column_name
            for column_name in operational_columns
            if column_name not in dataframe.columns
        ]

        if missing_operational_columns:
            raise PipelineExecutionError(
                f"Canonical table {logical_table_name!r} is missing "
                f"operational columns: {missing_operational_columns}"
            )

        resolved_publish_columns = list(
            dict.fromkeys(
                [
                    *publish_columns,
                    *operational_columns,
                ]
            )
        )

        published_frame = dataframe[
            resolved_publish_columns
        ].copy()

        duplicate_columns = published_frame.columns[
            published_frame.columns.duplicated()
        ].tolist()

        if duplicate_columns:
            raise PipelineExecutionError(
                f"Canonical publication for "
                f"{logical_table_name!r} contains duplicate "
                f"columns: {duplicate_columns}"
            )

        return published_frame
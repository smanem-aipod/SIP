from __future__ import annotations

from datetime import datetime, timezone

from sip_automation.core.config import ConfigManager
from sip_automation.core.exceptions import PipelineExecutionError
from sip_automation.core.logging import (
    bind_run_context,
    clear_log_context,
    get_logger,
)
from sip_automation.core.run_context import RunContext
from sip_automation.loaders.loader_factory import LoaderFactory
from sip_automation.pipeline.canonical_pipeline import (
    CanonicalPipeline,
)
from sip_automation.pipeline.models import PipelineRunResult
from sip_automation.pipeline.raw_load_pipeline import (
    RawLoadPipeline,
)


logger = get_logger(__name__)


class PipelineRunner:
    """
    Application-facing coordinator for the complete data preparation flow.

    Future callers:
    - command-line script
    - FastAPI upload endpoint
    - scheduled batch job
    - test suite
    """

    def __init__(
        self,
        *,
        config: ConfigManager,
        loader_factory: LoaderFactory,
        raw_pipeline: RawLoadPipeline,
        canonical_pipeline: CanonicalPipeline,
    ) -> None:
        self.config = config
        self.loader_factory = loader_factory
        self.raw_pipeline = raw_pipeline
        self.canonical_pipeline = canonical_pipeline

    def run(
        self,
        *,
        context: RunContext,
    ) -> PipelineRunResult:
        result = PipelineRunResult(
            run_id=context.run_id,
            initiated_by=context.initiated_by,
            started_at=context.started_at,
        )

        bind_run_context(
            run_id=str(context.run_id),
            initiated_by=context.initiated_by,
            fiscal_year=context.fiscal_year,
        )

        logger.info(
            "data_preparation_pipeline_started",
            application=self.config.get_application_name(),
            application_version=(
                self.config.get_application_version()
            ),
            environment=self.config.get_environment(),
        )

        try:
            result.raw_results = (
                self.raw_pipeline.run(
                    context=context
                )
            )

            result.canonical_results = (
                self.canonical_pipeline.run(
                    context=context
                )
            )

            result.status = "COMPLETED"
            result.completed_at = datetime.now(
                timezone.utc
            )

            logger.info(
                "data_preparation_pipeline_completed",
                status=result.status,
                raw_table_count=len(result.raw_results),
                canonical_table_count=len(
                    result.canonical_results
                ),
                raw_row_count=result.raw_row_count,
                canonical_row_count=(
                    result.canonical_row_count
                ),
                duration_seconds=(
                    result.completed_at
                    - result.started_at
                ).total_seconds(),
            )

            return result

        except Exception as exc:
            result.status = "FAILED"
            result.error_message = str(exc)
            result.completed_at = datetime.now(
                timezone.utc
            )

            logger.exception(
                "data_preparation_pipeline_failed",
                status=result.status,
                error_type=type(exc).__name__,
                duration_seconds=(
                    result.completed_at
                    - result.started_at
                ).total_seconds(),
            )

            if isinstance(exc, PipelineExecutionError):
                raise

            raise PipelineExecutionError(
                f"Data preparation pipeline failed for "
                f"run {context.run_id}."
            ) from exc

        finally:
            self.loader_factory.close()
            clear_log_context()
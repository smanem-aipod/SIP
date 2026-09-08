from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID
from sip_automation.container import ApplicationContainer
from sip_automation.core.config import (
    ConfigManager,
    get_config_manager,
)
from sip_automation.core.logging import configure_logging, get_logger
from sip_automation.core.run_context import RunContext
from sip_automation.pipeline.models import PipelineRunResult
from sip_automation.core.uploaded_files import UploadedFiles

logger = get_logger(__name__)


@dataclass
class SIPApplication:
    """
    Public application interface.

    Scripts, API routes, scheduled jobs, and tests should interact with
    this class rather than manually constructing repositories and pipelines.
    """

    container: ApplicationContainer

    @property
    def config(self) -> ConfigManager:
        return self.container.config

    def run_data_preparation(
        self,
        *,
        initiated_by: str,
        runtime_overrides: dict[str, Any] | None = None,
        uploaded_files: UploadedFiles | None = None,
    ) -> PipelineRunResult:
        """
        Execute the complete data-preparation pipeline:

        source
        → raw tables
        → canonical preparation
        → canonical tables
        """

        context = RunContext.from_config(
            self.config,
            initiated_by=initiated_by,
            overrides=runtime_overrides,
            uploaded_files=uploaded_files,
        )

        logger.info(
            "application_data_preparation_requested",
            run_id=str(context.run_id),
            initiated_by=initiated_by,
        )

        return self.container.pipeline_runner.run(
            context=context,
        )

    def run_raw_loading(
        self,
        *,
        initiated_by: str,
        runtime_overrides: dict[str, Any] | None = None,
        uploaded_files: UploadedFiles | None = None,
        run_id: UUID | None = None,
    ):
        """
        Execute only the source-to-raw portion.

        Mainly useful during development, diagnostics, and isolated testing.
        """

        context = RunContext.from_config(
            self.config,
            initiated_by=initiated_by,
            overrides=runtime_overrides,
            uploaded_files=uploaded_files,
            run_id=run_id,
        )

        logger.info(
            "application_raw_loading_requested",
            run_id=str(context.run_id),
            initiated_by=initiated_by,
            uploaded_file_count=(
                len(uploaded_files.files)
                if uploaded_files is not None
                else 0
            ),
        )

        return self.container.raw_pipeline.run(
            context=context,
        )

    def run_canonical_preparation(
        self,
        *,
        context: RunContext,
    ):
        """
        Execute only raw-to-canonical preparation for an existing run.

        The supplied context must use the same run_id as the rows already
        stored in the raw tables.
        """

        return self.container.canonical_pipeline.run(
            context=context,
        )
    def run_sip_calculations(
        self,
        *,
        context: RunContext,
    ):
        """
        Execute SIP calculations for canonical data belonging to an
        existing pipeline run.
        """

        logger.info(
            "application_sip_calculations_requested",
            run_id=str(context.run_id),
            initiated_by=context.initiated_by,
        )

        result = self.container.metric_pipeline.run(
            context=context,
        )

        logger.info(
            "application_sip_calculations_completed",
            run_id=str(context.run_id),
            calculated_row_count=(
                result.calculated_row_count
            ),
            published_row_count=(
                result.published_row_count
            ),
        )

        return result


    def close(self) -> None:
        self.container.close()

    def __enter__(self) -> "SIPApplication":
        return self

    def __exit__(
        self,
        exception_type,
        exception_value,
        traceback,
    ) -> None:
        self.close()


def create_application(
    *,
    config: ConfigManager | None = None,
) -> SIPApplication:
    """
    Configure logging and build the complete SIP application.

    This is the standard application entry point.
    """

    resolved_config = config or get_config_manager()

    configure_logging(
        resolved_config,
    )

    container = ApplicationContainer.build(
        config=resolved_config,
    )

    logger.info(
        "sip_application_created",
        application_name=(
            resolved_config.get_application_name()
        ),
        application_version=(
            resolved_config.get_application_version()
        ),
        environment=(
            resolved_config.get_environment()
        ),
    )

    return SIPApplication(
        container=container,
    )
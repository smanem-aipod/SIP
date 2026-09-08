from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine

from sip_automation.core.config import (
    ConfigManager,
    get_config_manager,
)
from sip_automation.database.canonical_repository import (
    CanonicalRepository,
)
from sip_automation.database.engine import get_database_engine
from sip_automation.database.raw_repository import RawRepository
from sip_automation.database.reference_repository import (
    ReferenceRepository,
)
from sip_automation.loaders.loader_factory import LoaderFactory
from sip_automation.pipeline.canonical_pipeline import (
    CanonicalPipeline,
)
from sip_automation.pipeline.metric_pipeline import MetricPipeline
from sip_automation.pipeline.pipeline_runner import PipelineRunner
from sip_automation.pipeline.raw_load_pipeline import RawLoadPipeline
from sip_automation.processing.datatype_converter import (
    DataTypeConverter,
)
from sip_automation.processing.enricher import EnrichmentEngine
from sip_automation.processing.transformer import (
    TransformationEngine,
)


@dataclass
class ApplicationContainer:
    """
    Dependency container for the SIP Automation application.
    """

    config: ConfigManager
    database_engine: Engine

    raw_repository: RawRepository
    canonical_repository: CanonicalRepository
    reference_repository: ReferenceRepository

    loader_factory: LoaderFactory

    datatype_converter: DataTypeConverter
    transformation_engine: TransformationEngine
    enrichment_engine: EnrichmentEngine

    raw_pipeline: RawLoadPipeline
    canonical_pipeline: CanonicalPipeline
    metric_pipeline: MetricPipeline
    pipeline_runner: PipelineRunner

    @classmethod
    def build(
        cls,
        *,
        config: ConfigManager | None = None,
        database_engine: Engine | None = None,
    ) -> "ApplicationContainer":
        resolved_config = (
            config
            or get_config_manager()
        )

        resolved_engine = (
            database_engine
            or get_database_engine()
        )

        raw_repository = RawRepository(
            resolved_engine,
            resolved_config,
        )

        canonical_repository = CanonicalRepository(
            resolved_engine,
            resolved_config,
        )

        reference_repository = ReferenceRepository(
            resolved_engine,
            resolved_config,
        )

        loader_factory = LoaderFactory(
            resolved_config,
        )

        datatype_converter = DataTypeConverter()

        transformation_engine = TransformationEngine()

        enrichment_engine = EnrichmentEngine(
            config=resolved_config,
            reference_repository=reference_repository,
            canonical_repository=canonical_repository,
        )

        raw_pipeline = RawLoadPipeline(
            config=resolved_config,
            loader_factory=loader_factory,
            raw_repository=raw_repository,
            datatype_converter=datatype_converter,
        )

        canonical_pipeline = CanonicalPipeline(
            config=resolved_config,
            raw_repository=raw_repository,
            canonical_repository=canonical_repository,
            transformation_engine=transformation_engine,
            enrichment_engine=enrichment_engine,
            datatype_converter=datatype_converter,
        )

        metric_pipeline = MetricPipeline(
            config=resolved_config,
            canonical_repository=canonical_repository,
            reference_repository=reference_repository,
        )

        pipeline_runner = PipelineRunner(
            config=resolved_config,
            loader_factory=loader_factory,
            raw_pipeline=raw_pipeline,
            canonical_pipeline=canonical_pipeline,
        )

        return cls(
            config=resolved_config,
            database_engine=resolved_engine,
            raw_repository=raw_repository,
            canonical_repository=canonical_repository,
            reference_repository=reference_repository,
            loader_factory=loader_factory,
            datatype_converter=datatype_converter,
            transformation_engine=transformation_engine,
            enrichment_engine=enrichment_engine,
            raw_pipeline=raw_pipeline,
            canonical_pipeline=canonical_pipeline,
            metric_pipeline=metric_pipeline,
            pipeline_runner=pipeline_runner,
        )

    def close(self) -> None:
        self.loader_factory.close()

    def __enter__(self) -> "ApplicationContainer":
        return self

    def __exit__(
        self,
        exception_type,
        exception_value,
        traceback,
    ) -> None:
        self.close()
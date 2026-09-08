from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import UUID

from sip_automation.processing.validator import ValidationReport


@dataclass(frozen=True)
class RawTableResult:
    """
    Result of loading and publishing one logical table to the raw layer.
    """

    logical_table_name: str
    provider_name: str
    source_name: str | None

    source_row_count: int
    raw_row_count: int
    raw_column_count: int

    schema_name: str
    table_name: str


@dataclass(frozen=True)
class CanonicalTableResult:
    """
    Result of preparing and publishing one canonical table.
    """

    logical_table_name: str

    source_row_count: int
    canonical_row_count: int
    canonical_column_count: int

    schema_name: str
    table_name: str

    pre_enrichment_validation: ValidationReport
    final_validation: ValidationReport


@dataclass(frozen=True)
class MetricPipelineResult:
    """
    Result of executing SIP metrics for one pipeline run.
    """

    run_id: UUID

    enabled_roles: list[str]
    role_row_counts: dict[str, int]

    calculated_row_count: int
    published_row_count: int

    engine_column_count: int
    published_column_count: int

    output_directory: Path
    output_paths: dict[str, Path]


@dataclass
class PipelineRunResult:
    """
    Complete result for one end-to-end data preparation run.
    """

    run_id: UUID
    initiated_by: str

    started_at: datetime
    completed_at: datetime | None = None

    raw_results: dict[str, RawTableResult] = field(
        default_factory=dict
    )

    canonical_results: dict[
        str,
        CanonicalTableResult,
    ] = field(
        default_factory=dict
    )

    metric_result: MetricPipelineResult | None = None

    status: str = "RUNNING"
    error_message: str | None = None

    @property
    def raw_row_count(self) -> int:
        return sum(
            result.raw_row_count
            for result in self.raw_results.values()
        )

    @property
    def canonical_row_count(self) -> int:
        return sum(
            result.canonical_row_count
            for result in self.canonical_results.values()
        )

    @property
    def metric_row_count(self) -> int:
        if self.metric_result is None:
            return 0

        return self.metric_result.published_row_count
"""
Configuration-driven data preparation components.

The processing package maps source data into raw-table contracts, cleans
and converts raw data, validates canonical datasets, creates derived
columns, and enriches datasets using configured reference tables.
"""

from sip_automation.processing.canonical_builder import CanonicalBuilder
from sip_automation.processing.datatype_converter import DataTypeConverter
from sip_automation.processing.enricher import EnrichmentEngine
from sip_automation.processing.preprocessing import DataPreprocessor
from sip_automation.processing.source_mapper import SourceMapper
from sip_automation.processing.transformer import TransformationEngine
from sip_automation.processing.validator import (
    TableValidator,
    ValidationIssue,
    ValidationReport,
)

__all__ = [
    "CanonicalBuilder",
    "DataPreprocessor",
    "DataTypeConverter",
    "EnrichmentEngine",
    "SourceMapper",
    "TableValidator",
    "TransformationEngine",
    "ValidationIssue",
    "ValidationReport",
]
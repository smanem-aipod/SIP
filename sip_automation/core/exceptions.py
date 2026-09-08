class SIPAutomationError(Exception):
    """Base exception for the SIP Automation application."""


# =========================================================
# Configuration errors
# =========================================================

class ConfigurationError(SIPAutomationError):
    """Raised when application configuration is invalid."""


class ConfigurationFileNotFoundError(ConfigurationError):
    """Raised when a required configuration file cannot be found."""


class ConfigurationValidationError(ConfigurationError):
    """Raised when configuration content does not satisfy its contract."""


class TableConfigurationError(ConfigurationError):
    """Raised when a logical table is incorrectly configured."""


class RuntimeParameterError(ConfigurationError):
    """Raised when a required runtime parameter is unavailable."""


# =========================================================
# Loader errors
# =========================================================

class LoaderError(SIPAutomationError):
    """Base exception for source loader failures."""


class LoaderNotFoundError(LoaderError):
    """Raised when no loader implementation exists for a provider."""


class SourceNotConfiguredError(LoaderError):
    """Raised when a table has no source configuration."""


class SourceFileNotFoundError(LoaderError):
    """Raised when a configured source file does not exist."""


class SourceTableNotFoundError(LoaderError):
    """Raised when a configured sheet, table, or endpoint does not exist."""


# =========================================================
# Mapping and processing errors
# =========================================================

class ProcessingError(SIPAutomationError):
    """Base exception for data-processing failures."""


class ColumnMappingError(ProcessingError):
    """Raised when source columns cannot be mapped to database columns."""


class DataCleaningError(ProcessingError):
    """Raised when configured cleaning operations fail."""


class DataTypeConversionError(ProcessingError):
    """Raised when values cannot be converted to configured datatypes."""


class TransformationError(ProcessingError):
    """Raised when a configured derived-column operation fails."""


class EnrichmentError(ProcessingError):
    """Raised when reference-table enrichment fails."""


# =========================================================
# Validation errors
# =========================================================

class ValidationError(SIPAutomationError):
    """Base exception for validation failures."""


class SchemaValidationError(ValidationError):
    """Raised when required columns are unavailable."""


class DataValidationError(ValidationError):
    """Raised when table data violates configured rules."""


# =========================================================
# Database errors
# =========================================================

class RepositoryError(SIPAutomationError):
    """Base exception for repository and database failures."""


class DatabaseObjectNotFoundError(RepositoryError):
    """Raised when a configured database table does not exist."""


class RawTableWriteError(RepositoryError):
    """Raised when data cannot be written to a raw table."""


class CanonicalTableWriteError(RepositoryError):
    """Raised when data cannot be written to a canonical table."""


class DatabaseReadError(RepositoryError):
    """Raised when data cannot be read from PostgreSQL."""


# =========================================================
# Pipeline errors
# =========================================================

class PipelineError(SIPAutomationError):
    """Base exception for pipeline execution failures."""


class PipelineDependencyError(PipelineError):
    """Raised when configured pipeline dependencies cannot be resolved."""


class PipelineExecutionError(PipelineError):
    """Raised when a pipeline stage fails."""


# =========================================================
# Precompute exceptions errors
# =========================================================

class PrecomputeExceptionError(SIPAutomationError):
    """Base exception for precompute-exceptions store failures."""


class PrecomputeExceptionValidationError(PrecomputeExceptionError):
    """Raised when a precompute exception payload is invalid."""


class PrecomputeExceptionNotFoundError(PrecomputeExceptionError):
    """Raised when a precompute exception id does not exist."""
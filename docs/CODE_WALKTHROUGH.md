# SIP Automation — Code Walkthrough

This document explains what every Python file under `src/sip_automation` does, in the
order the application actually executes them: startup, API request handling,
orchestration, raw ingestion, canonical building, SIP calculation, output, and the
shared database/utility layer.

## 1. Entry point / App startup

**`sip_automation/__init__.py`** is the package root. It re-exports `SIPApplication`,
`create_application`, and `ApplicationContainer` so the rest of the app (and any
external script) has a single, stable import surface instead of reaching into
submodules directly.

**`api/main.py`** builds the FastAPI app object. It mounts the versioned API router at
the root path, serves the static browser UI (`index.html`/`app.js`/`styles.css`) at
`/ui` with no-cache headers so UI changes are always picked up on reload, exposes a
`/health` endpoint, and disposes the cached application container cleanly on shutdown.

**`application.py`** defines `SIPApplication`, the single façade that scripts, the API,
and tests all call through. It exposes three high-level operations — run raw loading,
prepare canonical data, and calculate SIP — each delegating to the appropriate
pipeline from the DI container. `create_application()` is the composition root: it
sets up logging and builds the `ApplicationContainer`.

**`container.py`** holds `ApplicationContainer`, a dataclass-based dependency-injection
container. It is responsible for constructing the SQLAlchemy engine, the raw/canonical/
reference repositories, the loader factory, the processing engines, and the three
pipelines (raw load, canonical, metric), wiring them all together once per process.

**`core/config.py`** implements `ConfigManager`, which loads, validates, and caches
`application.yaml` and the other YAML config files (table registrations, source
configs, pipeline ordering, database object mappings). Everything else in the app asks
this class for configuration rather than reading YAML directly.

**`core/settings.py`** is a Pydantic `Settings` class populated from environment
variables (typically via `.env`). It holds the Postgres connection parameters and pool
sizing, and builds the final SQLAlchemy connection URL used by `database/engine.py`.

**`core/run_context.py`** defines `RunContext`, an immutable object that represents one
execution ("run") of the pipeline: its run id, who initiated it, any runtime
parameters, and any uploaded files. It is threaded through every pipeline stage so each
stage knows which run it's operating on and supports dotted-path parameter lookups.

**`core/logging.py`** configures `structlog` and the stdlib logging module based on
`logging.yaml`, setting up console and rotating file handlers with either JSON or
human-readable console output. It also provides helpers to bind/clear run-specific
logging context so log lines can be filtered by run id.

**`core/exceptions.py`** is the central exception hierarchy for the whole application —
a base `SIPAutomationError` with subclasses for configuration errors, loader errors,
processing errors, validation errors, repository errors, and pipeline errors. All
layers raise these instead of generic exceptions so the API layer can map them to
sensible HTTP responses.

**`core/uploaded_files.py`** defines `UploadedFiles`, a small immutable mapping from
logical table name (e.g. `employee`, `bp`, `sales`) to the path of a file the user
uploaded through the UI. This lets the raw-load stage override the configured Excel
source with whatever the user just uploaded for that run.

## 2. API layer

**`api/dependencies.py`** provides the FastAPI dependency `get_application()`, wrapped
in `lru_cache` so the same `SIPApplication` (and its underlying DI container) is reused
across requests instead of being rebuilt every time.

**`api/router.py`** is a thin aggregator that mounts the `runs` and `results` routers
under the `/api/v1` prefix, giving the app a single router to include in `main.py`.

**`api/endpoints/runs.py`** implements the run lifecycle endpoints: `POST /runs` accepts
the five uploaded Excel files (employee, bp, sales, nacs_guarantee, ytd_payments),
stores them, and triggers raw loading; `POST /runs/{run_id}/canonical` builds the
canonical tables for that run; `POST /runs/{run_id}/calculations` runs the SIP
calculation pipeline and returns which roles were enabled and their row counts. This
file also handles file validation and maps internal exceptions to HTTP error responses.

**`api/endpoints/results.py`** implements `GET /runs/{run_id}/results`, which reads the
CSV already written by the metric pipeline for a given role (or `all`) and returns the
rows as JSON, and `GET /runs/{run_id}/results/download`, which streams that same CSV
file back for download. No results are stored separately — the path is reconstructed
deterministically from the run id and role.

**`api/schemas/responses.py`** (the file you attached) defines the Pydantic response
models used across the API: `HealthResponse` for `/health`, `RawLoadResponse` and
`PipelineStageResponse` for the raw-load and canonical stages, `MetricPipelineResponse`
for the calculation stage, `ResultsResponse` for the results endpoint, and
`ErrorResponse` for consistent error payloads. These models are what actually shape the
JSON the browser UI's `app.js` parses.

## 3. Orchestration layer

**`pipeline/pipeline_runner.py`** implements `PipelineRunner`, which coordinates the
data-preparation half of a run: it runs raw loading, then canonical preparation, binds
and clears structured-log context around the run, aggregates everything into a
`PipelineRunResult`, and ensures loaders are closed when done.

**`pipeline/models.py`** contains the plain dataclasses used to represent pipeline
outcomes — `RawTableResult`, `CanonicalTableResult`, `MetricPipelineResult`, and the
top-level `PipelineRunResult` — along with helpers to aggregate row counts across
tables.

## 4. Data ingestion (raw load)

**`pipeline/raw_load_pipeline.py`** implements `RawLoadPipeline`. For every table
configured for raw loading, it picks the correct loader via the factory, pulls the
source DataFrame, maps source columns to raw-table columns using `SourceMapper`,
applies minimal cleaning/type coercion, and appends the result into the corresponding
raw PostgreSQL table.

**`loaders/base_loader.py`** defines the abstract `BaseLoader` interface and the
`LoadResult` dataclass that every concrete loader must return. The contract is
intentionally "dumb" — loaders preserve raw source headers and values with no business
logic applied.

**`loaders/loader_factory.py`** implements `LoaderFactory`, which resolves, creates, and
caches the correct loader implementation for a given logical table or provider name.
Currently only the `excel` provider exists, but the factory is written to support
registering additional providers (e.g. a future Snowflake or Workday loader) without
touching calling code.

**`loaders/excel_loader.py`** implements `ExcelLoader`, which reads the configured Excel
workbook/sheet (or a file uploaded through the UI) into a raw DataFrame using the fast
`calamine` engine. It validates that the workbook and sheet exist and merges
provider-level, workbook-level, and table-level `read_options` before parsing.

## 5. Canonical data building

**`pipeline/canonical_pipeline.py`** implements `CanonicalPipeline`. For every table in
the configured `canonical_build_order`, it reads the raw rows for the run, builds the
canonical frame, preprocesses and type-converts it, validates it, applies pre- and
post-enrichment derived columns and reference lookups, fills in any unresolved columns,
re-validates, and publishes the configured columns into the canonical table. It also
enforces that tables are built in a dependency-safe order.

**`processing/source_mapper.py`** implements `SourceMapper`, which maps
provider-specific source headers to stable raw-table columns using configured aliases
and header normalization. It also injects generated values, runtime-parameter values,
and constants, and stamps every row with the `pipeline_run_id`.

**`processing/canonical_builder.py`** implements `CanonicalBuilder`, which performs the
straightforward raw-to-canonical column rename/copy described by each table's
`raw_to_canonical.direct_mappings` config. It contains no derived or business logic —
that lives in the transformer and enricher.

**`processing/preprocessing.py`** implements `DataPreprocessor`, a generic,
config-driven cleaning step: it strips and collapses whitespace, normalizes unicode and
null markers and casing, removes empty rows and repeated embedded header rows, and
applies any configured value mappings.

**`processing/datatype_converter.py`** implements `DataTypeConverter`, which converts
each column to its configured type — string, integer, decimal, percentage, date,
timestamp, boolean, or currency code — per the table's YAML contract, enforcing
precision/scale and raising an error on invalid values rather than silently coercing.

**`processing/validator.py`** implements `TableValidator` along with `ValidationReport`
and `ValidationIssue`. It checks required columns, nullability, simple and composite
uniqueness, accepted-value lists, regex patterns, numeric ranges, and date-ordering
rules, all driven by table configuration.

**`processing/transformer.py`** implements `TransformationEngine`, a registry of
config-driven derived-column operations. This is where most of the SIP-specific
business rules live: sum/multiply/safe-divide/concat/coalesce, constants, runtime
parameters, subtract, minimum, copy, add-days, prorate, and specialized rules like
employee SIP-eligible date calculation, NACS eligibility-month rules, and GP-flag
classification. Operations run in either a "before enrichment" or "after enrichment"
stage.

**`processing/enricher.py`** implements `EnrichmentEngine`, which performs
config-driven reference-table joins — adding columns from reference or canonical
datasets via keyed merges, flagging match status, and validating merge cardinality. It
also implements a specialized `conditional_assignment_aggregate` operation used for
BDM-style assignment aggregation with required/optional matching keys and percentage
sharing.

## 6. Calculation engine (SIP metrics)

**`pipeline/metric_pipeline.py`** implements `MetricPipeline`. It loads the canonical
employee, bp, sales, fx_rates, nacs_guarantee, ytd_payments, and bdm data for the run,
normalizes join-key strings, runs the metric engine once per enabled role (as defined
in `role_mappings.yaml`), and writes both per-role and combined outputs to Parquet and
CSV under `outputs/metric_engine/{run_id}/`.

**`calculation_engine/config_loader.py`** implements `CalculationConfigLoader`, which
loads the metric library from `sip_metrics.yaml` and the role bindings from
`role_mappings.yaml`, then resolves any `role_mapping:` placeholders in the metric
definitions against each role's bindings to produce one fully executable
`ResolvedMetricPlan` per role.

**`calculation_engine/models.py`** holds the dataclasses that represent the metric
domain model: `MetricDefinition` and `MetricLibrary` (the raw metric catalog),
`RoleMapping` (a role's population and bindings), and `ResolvedMetricPlan` (the final,
placeholder-resolved plan actually executed for a role).

**`calculation_engine/context.py`** implements `CalculationContext`, which holds all
the input DataFrames (employee, bp, sales, fx_rates, nacs_guarantee, ytd_payments,
bdm), runtime parameters, and static reference data for a calculation run, exposing
`get_dataset`, `get_parameter`, and `get_static_reference` accessors that operations use
via dotted-path lookups.

**`calculation_engine/registry.py`** implements `OperationRegistry`, a simple mapping
from operation names (as written in the metrics YAML) to their `BaseOperation`
implementations. It supports registering custom operations and validating that a
referenced operation name actually exists.

**`calculation_engine/dependency_graph.py`** implements `MetricDependencyGraph`, which
builds both explicit and inferred dependencies between metrics and computes a
topological execution order using Kahn's algorithm, raising `MetricDependencyError` if
it finds an unknown or cyclic dependency.

**`calculation_engine/validators.py`** implements `MetricPlanValidator`, which validates
a resolved plan before it is executed: plan metadata, population configuration, metric
names and sections, whether referenced operations are actually registered, any
unresolved `role_mapping` placeholders, dependency sanity, and uniqueness of output
column names.

**`calculation_engine/engine.py`** implements `MetricEngine`, the actual executor. It
validates the plan, builds the role's population from the configured dataset and
filters, then executes each metric in dependency order, appending each result as a new
column, and finally renames internal metric names to their business-facing
`output_name`s.

**`calculation_engine/operations/base.py`** defines `BaseOperation`, the abstract base
class every operation extends. It provides shared logic for resolving operands (column
reference, literal value, runtime parameter, or static reference), resolving lists of
inputs, coercing values to numeric types, and checking that required columns are
present.

**`calculation_engine/operations/constant.py`** implements `ConstantOperation`, which
simply returns a constant value as a Series, sourced either from a literal `value` or
from a `static_reference` lookup.

**`calculation_engine/operations/arithmetic.py`** implements the basic numeric
operations: `AddOperation`, `SubtractOperation`, `MultiplyOperation`,
`DivideOperation` (with safe zero-handling), `MinimumOperation`, `MaximumOperation`,
and `AbsoluteOperation`, all working over resolved operands.

**`calculation_engine/operations/aggregate.py`** (the file you attached earlier)
implements `BaseAggregateOperation` and its subclasses — sum, average, minimum,
maximum, count, and weighted average — for grouped aggregation over a configurable
source dataset with filters and key mapping back to the population. It also implements
`WeightedAllocationSumOperation`, which allocates a grouped actual amount across
entities according to their share of a BP target within the group (used for CAM-style
allocation).

**`calculation_engine/operations/conditional.py`** implements `ConditionalSupport` (a
shared condition evaluator supporting `all`/`any` combinators, comparison operators,
`in`, and `is_null` checks), along with `IfElseOperation` and `CaseWhenOperation` for
conditional value assignment.

**`calculation_engine/operations/lookup.py`** implements `LookupOperation`, a keyed
merge that pulls a single value column from a reference dataset (with cardinality
validation), and `ExistsOperation`, a boolean existence check against a reference
dataset.

**`calculation_engine/operations/financial.py`** implements the SIP-specific financial
control operations: `CapOperation`, `FloorOperation`, `ClampOperation`,
`ProrateOperation`, `RoundOperation`, `OverpaymentOperation` (the overpayment recapture
formula), and `NacsRegionCurrencyOperation` (the NACS region-currency SIP-earned
formula, including guarantee and quarterly-payment deductions).

**`calculation_engine/operations/fiscal.py`** implements `MonthsEligibleOperation`,
which computes how many months an employee is SIP-eligible within a fiscal year or
quarter, using fiscal month-value tables and quarter/annual cutoff-date rules.

## 7. Output/export layer

**`calculation_engine/output_formatter.py`** implements `SIPOutputFormatter` along with
`OutputLayout` and `OutputColumn`. It loads `sip_output_layout.yaml` and rearranges a
calculation result DataFrame into the exact column order and headers finance expects,
supporting duplicate headers and a configurable policy for missing columns (error, add
as null, or skip). The actual CSV/Parquet writing happens in `MetricPipeline`'s
`_save_csv`/`_save_parquet` methods, not in this file.

## 8. Database / utilities layer

**`database/engine.py`** creates and caches the SQLAlchemy engine from `Settings`, and
provides `database_connection`/`database_transaction` context managers along with
`check_database_connection` and `dispose_database_engine`.

**`database/base_repository.py`** implements `BaseRepository`, the shared base for all
repositories: safe identifier validation, a generic `read_table` method with
parameterized filters/columns/ordering, and `append_dataframe`, which does a
schema-validated bulk insert via PostgreSQL `COPY` with a chunked-`INSERT` fallback. It
also handles pandas/NumPy-to-PostgreSQL value normalization.

**`database/raw_repository.py`** implements `RawRepository`, which handles inserting
into and reading from `raw.*` tables, resolving the correct schema/table name from
config.

**`database/canonical_repository.py`** implements `CanonicalRepository`, the equivalent
of `RawRepository` for `canonical.*` tables.

**`database/reference_repository.py`** implements `ReferenceRepository`, providing
read-only access to reference tables, with convenience methods `read_fx_rates` and
`read_employee_seller_bridge`.

**`database/schema_inspector.py`** implements `DatabaseSchemaInspector` along with
`TableMetadata` and `ColumnMetadata`. It inspects PostgreSQL table existence, columns,
and primary keys, and validates that a DataFrame's columns are compatible with the
destination table before an insert is attempted.

## End-to-end flow

Putting it all together, a single run flows as:

`api/main.py` receives the request → `api/endpoints/runs.py` handles it →
`application.py` (`SIPApplication`) is called → `pipeline/pipeline_runner.py`
coordinates raw load and canonical prep → `pipeline/raw_load_pipeline.py` (using
`loaders/`) loads Excel into raw tables → `pipeline/canonical_pipeline.py` (using
`processing/`) builds canonical tables → `pipeline/metric_pipeline.py` runs
`calculation_engine/engine.py` (using `operations/*`) per role → results are arranged
by `output_formatter.py` and written to CSV/Parquet → `api/endpoints/results.py` reads
those files back on request → the browser UI (`app.js`/`index.html`) renders the JSON
response shaped by `api/schemas/responses.py`.

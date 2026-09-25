from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml

from sip_automation.calculation_engine.output_formatter import (
    SIPOutputFormatter,
)

from sip_automation.calculation_engine import (
    CalculationConfigLoader,
    CalculationContext,
    MetricEngine,
)
from sip_automation.calculation_engine.models import ResolvedMetricPlan
from sip_automation.core.config import ConfigManager
from sip_automation.core.cam_allocation_overrides import (
    CAMAllocationOverridesStore,
    build_cam_overrides_dataframe,
)
from sip_automation.core.exceptions import PipelineExecutionError
from sip_automation.core.logging import get_logger
from sip_automation.core.hr_exclusions import HRExclusionsStore
from sip_automation.core.precompute_exceptions import (
    PrecomputeExceptionsStore,
    build_adjustment_dataset,
)
from sip_automation.core.run_context import RunContext
from sip_automation.database.canonical_repository import CanonicalRepository
from sip_automation.database.reference_repository import ReferenceRepository
from sip_automation.pipeline.models import MetricPipelineResult


logger = get_logger(__name__)


class MetricPipeline:
    """
    Execute the configured SIP metric calculations for one pipeline run.

    Flow:
        canonical employee/bp/sales
        → technical normalization
        → role-specific metric plans
        → metric execution
        → published SIP outputs
        → CSV and Parquet files
    """

    def __init__(
        self,
        *,
        config: ConfigManager,
        canonical_repository: CanonicalRepository,
        reference_repository: ReferenceRepository,
    ) -> None:
        self.config = config
        self.canonical_repository = canonical_repository
        self.reference_repository = reference_repository

        project_root = self.config.config_root.parent

        self.sip_metrics_path = (
            self.config.config_root
            / "calculations"
            / "sip_metrics.yaml"
        )

        self.role_mappings_path = (
            self.config.config_root
            / "calculations"
            / "role_mappings.yaml"
        )
        self.sip_output_layout_path = (
            self.config.config_root
            / "sip_output_layout.yaml"
        )
        self.output_root = (
            project_root
            / "outputs"
            / "metric_engine"
        )

    def run(
        self,
        *,
        context: RunContext,
    ) -> MetricPipelineResult:
        """
        Execute SIP calculations for canonical rows belonging to one run_id.
        """

        run_output_directory = (
            self.output_root
            / str(context.run_id)
        )

        run_output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        logger.info(
            "metric_pipeline_started",
            **context.as_log_context(),
            output_directory=str(run_output_directory),
        )

        try:
            employee = self._load_canonical_table(
                logical_table_name="employee",
                context=context,
            )
            employee = self._apply_hr_exclusions(employee)

            bp = self._load_canonical_table(
                logical_table_name="bp",
                context=context,
            )

            sales = self._load_canonical_table(
                logical_table_name="sales",
                context=context,
            )
            fx_rates = self.reference_repository.read_fx_rates()
            nacs_guarantee = self._load_canonical_table(
                logical_table_name="nacs_guarantee",
                context=context,
            )

            ytd_payments = self._load_canonical_table(
                logical_table_name="ytd_payments",
                context=context,
            )

            bdm = self._load_canonical_table(
                logical_table_name="bdm",
                context=context,
            )

            (
                employee,
                bp,
                sales,
                fx_rates,
                nacs_guarantee,
                ytd_payments,
                bdm,
            ) = self._prepare_datasets(
                employee=employee,
                bp=bp,
                sales=sales,
                fx_rates=fx_rates,
                nacs_guarantee=nacs_guarantee,
                ytd_payments=ytd_payments,
                bdm=bdm,

            )

            precompute_exceptions = (
                self._load_precompute_exceptions()
            )

            cam_allocation_overrides = (
                self._load_cam_allocation_overrides()
            )

            role_ids = self._load_enabled_role_ids()

            complete_role_results: list[pd.DataFrame] = []
            published_role_results: list[pd.DataFrame] = []

            role_row_counts: dict[str, int] = {}
            role_output_paths: dict[str, Path] = {}

            for role_id in role_ids:
                role_result, role_plan = self._run_role_metrics(
                    role_id=role_id,
                    employee=employee,
                    bp=bp,
                    sales=sales,
                    fx_rates=fx_rates,
                    nacs_guarantee=nacs_guarantee,
                    ytd_payments=ytd_payments,
                    bdm=bdm,
                    precompute_exceptions=precompute_exceptions,
                    cam_allocation_overrides=cam_allocation_overrides,
                    context=context,
                )

                role_row_counts[role_id] = len(role_result)

                if role_result.empty:
                    logger.info(
                        "metric_role_completed_empty",
                        **context.as_log_context(),
                        role_id=role_id,
                    )
                    continue

                role_metrics_path = self._save_parquet(
                    role_result,
                    output_directory=run_output_directory,
                    filename=f"{role_id}_all_metrics.parquet",
                )


                role_sip_output = SIPOutputFormatter.format(
                    role_result,
                    layout_path=self.sip_output_layout_path,
                    quarter=(
                        context.parameters.get("quarter") or "Q2"
                    ),
                )                

                role_sip_path = self._save_csv(
                    role_sip_output,
                    output_directory=run_output_directory,
                    filename=f"{role_id}_sip_output.csv",
                )

                role_output_paths[
                    f"{role_id}_all_metrics"
                ] = role_metrics_path

                role_output_paths[
                    f"{role_id}_sip_output"
                ] = role_sip_path

                complete_role_results.append(
                    role_result
                )

                published_role_results.append(
                    role_sip_output
                )

            if not complete_role_results:
                logger.warning(
                    "metric_pipeline_completed_without_rows",
                    **context.as_log_context(),
                    enabled_roles=role_ids,
                )

                return MetricPipelineResult(
                    run_id=context.run_id,
                    enabled_roles=role_ids,
                    role_row_counts=role_row_counts,
                    calculated_row_count=0,
                    published_row_count=0,
                    engine_column_count=0,
                    published_column_count=0,
                    output_directory=run_output_directory,
                    output_paths=role_output_paths,
                )

            combined_engine_result = pd.concat(
                complete_role_results,
                ignore_index=True,
                sort=False,
            )

            combined_sip_output = pd.concat(
                published_role_results,
                ignore_index=True,
                sort=False,
            )

            all_metrics_parquet_path = self._save_parquet(
                combined_engine_result,
                output_directory=run_output_directory,
                filename="all_role_metrics.parquet",
            )

            all_metrics_csv_path = self._save_csv(
                combined_engine_result,
                output_directory=run_output_directory,
                filename="all_role_metrics_preview.csv",
            )

            sip_parquet_path = self._save_parquet(
                combined_sip_output,
                output_directory=run_output_directory,
                filename="sip_calculations.parquet",
            )

            sip_csv_path = self._save_csv(
                combined_sip_output,
                output_directory=run_output_directory,
                filename="sip_calculations.csv",
            )

            output_paths = {
                **role_output_paths,
                "all_role_metrics_parquet": (
                    all_metrics_parquet_path
                ),
                "all_role_metrics_csv": (
                    all_metrics_csv_path
                ),
                "sip_calculations_parquet": (
                    sip_parquet_path
                ),
                "sip_calculations_csv": (
                    sip_csv_path
                ),
            }

            result = MetricPipelineResult(
                run_id=context.run_id,
                enabled_roles=role_ids,
                role_row_counts=role_row_counts,
                calculated_row_count=len(
                    combined_engine_result
                ),
                published_row_count=len(
                    combined_sip_output
                ),
                engine_column_count=len(
                    combined_engine_result.columns
                ),
                published_column_count=len(
                    combined_sip_output.columns
                ),
                output_directory=run_output_directory,
                output_paths=output_paths,
            )

            logger.info(
                "metric_pipeline_completed",
                **context.as_log_context(),
                enabled_roles=role_ids,
                calculated_row_count=(
                    result.calculated_row_count
                ),
                published_row_count=(
                    result.published_row_count
                ),
                engine_column_count=(
                    result.engine_column_count
                ),
                published_column_count=(
                    result.published_column_count
                ),
                output_directory=str(
                    result.output_directory
                ),
            )

            return result

        except Exception as exc:
            logger.exception(
                "metric_pipeline_failed",
                **context.as_log_context(),
                error_type=type(exc).__name__,
            )

            if isinstance(
                exc,
                PipelineExecutionError,
            ):
                raise

            raise PipelineExecutionError(
                f"SIP metric execution failed for run "
                f"{context.run_id}."
            ) from exc

    def _apply_hr_exclusions(self, employee: pd.DataFrame) -> pd.DataFrame:
        """Remove HR-excluded employees before SIP calculations."""
        store = HRExclusionsStore(
            self.config.config_root.parent / "data" / "hr_exclusions.yaml"
        )
        excluded_ids = store.load()
        if not excluded_ids:
            return employee
        # Compare case-insensitively - the exclusion list is normalized to
        # uppercase on save, but this also protects against any entries
        # saved before that normalization existed.
        excluded_set = {str(i).strip().upper() for i in excluded_ids}
        before = len(employee)
        employee = employee[
            ~employee["employee_id"].astype(str).str.strip().str.upper().isin(excluded_set)
        ].copy()
        logger.info(
            "hr_exclusions_applied",
            excluded_count=before - len(employee),
            remaining=len(employee),
        )
        return employee

    def _load_canonical_table(
        self,
        *,
        logical_table_name: str,
        context: RunContext,
    ) -> pd.DataFrame:
        dataframe = self.canonical_repository.read(
            logical_table_name,
            filters={
                "pipeline_run_id": context.run_id
            },
        )

        if dataframe.empty:
            logger.info(
                "metric_canonical_dataset_missing",
                **context.as_log_context(),
                logical_table_name=logical_table_name,
                reason="no_rows_for_run",
            )
            return dataframe

        logger.info(
            "metric_canonical_dataset_loaded",
            **context.as_log_context(),
            logical_table_name=logical_table_name,
            row_count=len(dataframe),
            column_count=len(dataframe.columns),
        )

        return dataframe

    def _load_precompute_exceptions(
        self,
    ) -> pd.DataFrame:
        exceptions = PrecomputeExceptionsStore().list()

        dataset = build_adjustment_dataset(exceptions)

        return self._normalize_string_columns(
            dataset,
            ["employee_id"],
        )

    def _load_cam_allocation_overrides(
        self,
    ) -> pd.DataFrame | None:
        store = CAMAllocationOverridesStore(
            path=self.config.config_root.parent / "data" / "cam_allocation_overrides.yaml"
        )
        overrides = store.list()
        return build_cam_overrides_dataframe(overrides)

    def _load_enabled_role_ids(
        self,
    ) -> list[str]:
        with self.role_mappings_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            role_config = yaml.safe_load(
                file
            ) or {}

        roles = role_config.get(
            "roles",
            {},
        )

        if not isinstance(roles, dict):
            raise PipelineExecutionError(
                "role_mappings.yaml must contain "
                "a 'roles' dictionary."
            )

        enabled_roles = [
            str(role_id)
            for role_id, definition in roles.items()
            if isinstance(definition, dict)
            and definition.get(
                "enabled",
                True,
            )
        ]

        if not enabled_roles:
            raise PipelineExecutionError(
                "No enabled calculation roles were found "
                "in role_mappings.yaml."
            )

        return enabled_roles

    def _build_role_plan(
        self,
        *,
        role_id: str,
        quarter: str | None = None,
    ) -> ResolvedMetricPlan:
        return CalculationConfigLoader.build_plan(
            metric_library_path=(
                self.sip_metrics_path
            ),
            role_mapping_path=(
                self.role_mappings_path
            ),
            role_id=role_id,
            quarter=quarter,
        )

    def _run_role_metrics(
        self,
        *,
        role_id: str,
        employee: pd.DataFrame,
        bp: pd.DataFrame,
        sales: pd.DataFrame,
        fx_rates: pd.DataFrame,
        nacs_guarantee: pd.DataFrame,
        ytd_payments: pd.DataFrame,
        bdm: pd.DataFrame,
        precompute_exceptions: pd.DataFrame,
        cam_allocation_overrides: pd.DataFrame | None,
        context: RunContext,
    ) -> tuple[
        pd.DataFrame,
        ResolvedMetricPlan,
    ]:
        logger.info(
            "metric_role_started",
            **context.as_log_context(),
            role_id=role_id,
        )

        plan = self._build_role_plan(
            role_id=role_id,
            # Same value used for the "quarter"/case_when branching and
            # the calculation_quarter column below - reused here so any
            # "{quarter}" placeholder in a metric's output_name (e.g.
            # "Guarantee SIP ({quarter})") resolves to the run's actual
            # selection rather than staying literal or defaulting wrong.
            quarter=(
                context.parameters.get("quarter") or "Q2"
            ),
        )

        logger.info(
            "metric_role_plan_created",
            **context.as_log_context(),
            role_id=role_id,
            plan_parameters=plan.parameters,
            context_parameters=context.parameters,
        )

        calculation_context = CalculationContext(
            employee=employee,
            bp=bp,
            sales=sales,
            fx_rates=fx_rates,
            nacs_guarantee=nacs_guarantee,
            ytd_payments=ytd_payments,
            bdm=bdm,
            precompute_exceptions=precompute_exceptions,
            cam_allocation_overrides=cam_allocation_overrides,
            pipeline_run_id=context.run_id,
            fiscal_year=None,
            quarter=None,
            parameters=context.parameters,
        )

        logger.info(
            "metric_calculation_context_created",
            **context.as_log_context(),
            role_id=role_id,
            calc_context_parameters=calculation_context.parameters,
        )

        metric_engine = MetricEngine()

        result = metric_engine.run(
            plan=plan,
            context=calculation_context,
            use_output_names=True,
        )

        result.insert(
            0,
            "calculation_role",
            role_id,
        )

        # Runtime overrides (context.parameters) take precedence over the
        # sip_metrics.yaml plan defaults - matches MetricEngine's own merge
        # order, so this reflects the quarter/fiscal_year actually used.
        result.insert(
            1,
            "calculation_quarter",
            context.parameters.get(
                "quarter",
                plan.parameters.get("quarter"),
            ),
        )

        result.insert(
            2,
            "calculation_fiscal_year",
            context.parameters.get(
                "fiscal_year",
                plan.parameters.get("fiscal_year"),
            ),
        )

        logger.info(
            "metric_role_completed",
            **context.as_log_context(),
            role_id=role_id,
            row_count=len(result),
            column_count=len(result.columns),
        )

        return result, plan

    @classmethod
    def _prepare_datasets(
        cls,
        *,
        employee: pd.DataFrame,
        bp: pd.DataFrame,
        sales: pd.DataFrame,
        fx_rates: pd.DataFrame,
        nacs_guarantee: pd.DataFrame,
        ytd_payments: pd.DataFrame,
        bdm: pd.DataFrame,
    ) -> tuple[
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
        pd.DataFrame,
    ]:
        employee = cls._normalize_string_columns(
            employee,
            [
                "employee_id",
                "preferred_name",
                "job_profile_for_sip",
                "sales_group_description",
                "sales_office_description",
                "payroll_currency",
                "country",
                "region",
                "bu",
            ],
        )
        employee = cls._uppercase_id_columns(
            employee,
            ["employee_id"],
        )

        bp = cls._normalize_string_columns(
            bp,
            [
                "employee_id",
                "employee_id_only_for_shared",
                "sales_group_description",
                "sales_office_description",
                "am_id",
                "dm_id",
                "cam_id",
                "bdm_id",
                "division_node",
            ],
        )
        # am_id/dm_id deliberately excluded - despite the name, these hold
        # the AM/DM's full name (e.g. "Torvik Noxen"), not an employee ID,
        # and aren't referenced as a join key anywhere in role_mappings.yaml
        # or sip_metrics.yaml (only cam_id/bdm_id are). Uppercasing them
        # would just corrupt a display value with no matching benefit.
        bp = cls._uppercase_id_columns(
            bp,
            [
                "employee_id",
                "employee_id_only_for_shared",
                "cam_id",
                "bdm_id",
            ],
        )

        sales = cls._normalize_string_columns(
            sales,
            [
                "employee_id",
                "sales_group_description",
                "sales_office_description",
                "profitcentersbudesc",
                "ship_to",
                "gp_flag",
                "low_margin_flag",
                "material",
            ],
        )
        sales = cls._uppercase_id_columns(
            sales,
            ["employee_id"],
        )
        fx_rates = cls._normalize_string_columns(
            fx_rates,
            [
                "currency_code",
            ],
        )        
        nacs_guarantee = cls._normalize_string_columns(
            nacs_guarantee,
            [
                "employee_id",
                "payroll_currency",
            ],
        )
        nacs_guarantee = cls._uppercase_id_columns(
            nacs_guarantee,
            ["employee_id"],
        )

        ytd_payments = cls._normalize_string_columns(
            ytd_payments,
            [
                "employee_id",
                "currency_code",
            ],
        )
        ytd_payments = cls._uppercase_id_columns(
            ytd_payments,
            ["employee_id"],
        )

        bdm = cls._normalize_string_columns(
            bdm,
            [
                "bdm_id",
            ],
        )
        bdm = cls._uppercase_id_columns(
            bdm,
            ["bdm_id"],
        )
                            
        return (
            employee,
            bp,
            sales,
            fx_rates,
            nacs_guarantee,
            ytd_payments,
            bdm,
        )

    @staticmethod
    def _normalize_string_columns(
        dataframe: pd.DataFrame,
        columns: list[str],
    ) -> pd.DataFrame:
        result = dataframe.copy()

        for column_name in columns:
            if column_name not in result.columns:
                continue

            result[column_name] = (
                result[column_name]
                .astype("string")
                .str.strip()
                .replace("", pd.NA)
            )

        return result

    @staticmethod
    def _uppercase_id_columns(
        dataframe: pd.DataFrame,
        columns: list[str],
    ) -> pd.DataFrame:
        """
        Uppercase known ID/key columns (after _normalize_string_columns has
        already stripped whitespace), so joins across independently
        exported source files - employee_id in employee vs bp vs sales;
        am_id/dm_id/cam_id/bdm_id in bp vs employee - match regardless of
        casing differences between exports. The exclusion store and this
        pipeline's HR-exclusion filter already uppercase employee_id before
        comparing; this closes the same gap for every other join key that
        feeds the calculation engine (see DEF-023).

        Deliberately scoped to ID columns only - NOT applied to free-text
        or display columns (preferred_name, job_profile_for_sip,
        descriptions), which either need to preserve their original
        casing for display, or already have their own normalization
        convention elsewhere (sales_group_description/
        sales_office_description are lowercased, not uppercased, in
        CanonicalPipeline._normalize_canonical_values).
        """
        result = dataframe.copy()

        for column_name in columns:
            if column_name not in result.columns:
                continue

            result[column_name] = (
                result[column_name].str.upper()
            )

        return result

    @staticmethod
    def _save_parquet(
        dataframe: pd.DataFrame,
        *,
        output_directory: Path,
        filename: str,
    ) -> Path:
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_directory
            / filename
        )

        dataframe.to_parquet(
            output_path,
            index=False,
            engine="pyarrow",
            compression="snappy",
        )

        return output_path.resolve()

    @staticmethod
    def _save_csv(
        dataframe: pd.DataFrame,
        *,
        output_directory: Path,
        filename: str,
    ) -> Path:
        output_directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        output_path = (
            output_directory
            / filename
        )

        dataframe.to_csv(
            output_path,
            index=False,
        )

        return output_path.resolve()
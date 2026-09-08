from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

import pandas as pd
import yaml
from dotenv import load_dotenv
from sqlalchemy import Engine, create_engine

from sip_automation.calculation_engine.output_formatter import (
    SIPOutputFormatter,
)

from sip_automation.calculation_engine import (
    CalculationConfigLoader,
    CalculationContext,
    MetricEngine,
)
from sip_automation.calculation_engine.models import (
    ResolvedMetricPlan,
)


# =========================================================
# PROJECT PATHS
# =========================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

SIP_METRICS_PATH = (
    PROJECT_ROOT
    / "config"
    / "calculations"
    / "sip_metrics.yaml"
)

ROLE_MAPPINGS_PATH = (
    PROJECT_ROOT
    / "config"
    / "calculations"
    / "role_mappings.yaml"
)

SIP_OUTPUT_LAYOUT_PATH = (
    PROJECT_ROOT
    / "config"
    / "sip_output_layout.yaml"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "outputs"
    / "metric_engine"
)

ENV_FILE_PATH = PROJECT_ROOT / ".env"


# =========================================================
# DATABASE OBJECTS
#
# These are infrastructure locations, not finance rules.
# They may also be overridden through .env.
# =========================================================

EMPLOYEE_SCHEMA = os.getenv(
    "SIP_EMPLOYEE_SCHEMA",
    "canonical",
)
EMPLOYEE_TABLE = os.getenv(
    "SIP_EMPLOYEE_TABLE",
    "employee",
)

BP_SCHEMA = os.getenv(
    "SIP_BP_SCHEMA",
    "canonical",
)
BP_TABLE = os.getenv(
    "SIP_BP_TABLE",
    "bp",
)

SALES_SCHEMA = os.getenv(
    "SIP_SALES_SCHEMA",
    "canonical",
)
SALES_TABLE = os.getenv(
    "SIP_SALES_TABLE",
    "sales",
)

FX_SCHEMA = os.getenv(
    "SIP_FX_SCHEMA",
    "core",
)
FX_TABLE = os.getenv(
    "SIP_FX_TABLE",
    "fact_fx_rate",
)
NACS_GUARANTEE_SCHEMA = "canonical"
NACS_GUARANTEE_TABLE = "nacs_guarantee"

YTD_PAYMENTS_SCHEMA = "canonical"
YTD_PAYMENTS_TABLE = "ytd_payments"

# =========================================================
# DATABASE CONNECTION
# =========================================================

def create_postgres_engine() -> Engine:
    """
    Create the SQLAlchemy PostgreSQL engine.

    Preferred:
        DATABASE_URL in .env

    Fallback:
        DB_HOST
        DB_PORT
        DB_NAME
        DB_USER
        DB_PASSWORD
    """

    load_dotenv(ENV_FILE_PATH)

    database_url = os.getenv("DATABASE_URL")

    if database_url:
        return create_engine(
            database_url,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )

    host = os.getenv(
        "DB_HOST",
        os.getenv(
            "POSTGRES_HOST",
            "localhost",
        ),
    )

    port = os.getenv(
        "DB_PORT",
        os.getenv(
            "POSTGRES_PORT",
            "5432",
        ),
    )

    database = os.getenv(
        "DB_NAME",
        os.getenv(
            "POSTGRES_DB",
            "SIP",
        ),
    )

    username = os.getenv(
        "DB_USER",
        os.getenv("POSTGRES_USERNAME"),
    )

    password = os.getenv(
        "DB_PASSWORD",
        os.getenv("POSTGRES_PASSWORD"),
    )

    if not username:
        raise RuntimeError(
            "Database username is missing. "
            "Set DB_USER, POSTGRES_USERNAME, "
            "or DATABASE_URL in .env."
        )

    if password is None:
        raise RuntimeError(
            "Database password is missing. "
            "Set DB_PASSWORD, POSTGRES_PASSWORD, "
            "or DATABASE_URL in .env."
        )

    encoded_username = quote_plus(username)
    encoded_password = quote_plus(password)

    connection_url = (
        "postgresql+psycopg2://"
        f"{encoded_username}:"
        f"{encoded_password}"
        f"@{host}:{port}/{database}"
    )

    return create_engine(
        connection_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
    )


# =========================================================
# CONFIGURATION
# =========================================================

def load_enabled_role_ids(
    role_mapping_path: Path,
) -> list[str]:
    """
    Read enabled role IDs directly from role_mappings.yaml.

    This prevents the runner from hardcoding Sales
    Professional, Area Manager, District Manager, CAM, BDM,
    or any future role.
    """

    with role_mapping_path.open(
        "r",
        encoding="utf-8",
    ) as file:
        config = yaml.safe_load(file) or {}

    roles = config.get("roles", {})

    if not isinstance(roles, dict):
        raise ValueError(
            "role_mappings.yaml must contain a "
            "'roles' dictionary."
        )

    enabled_roles = [
        str(role_id)
        for role_id, definition in roles.items()
        if isinstance(definition, dict)
        and definition.get("enabled", True)
    ]

    if not enabled_roles:
        raise ValueError(
            "No enabled roles were found in "
            "role_mappings.yaml."
        )

    return enabled_roles


# =========================================================
# DATA LOADING
# =========================================================

def load_table(
    engine: Engine,
    *,
    schema_name: str,
    table_name: str,
) -> pd.DataFrame:
    """
    Load a complete database table into pandas.
    """

    query = f'''
        SELECT *
        FROM "{schema_name}"."{table_name}"
    '''

    dataframe = pd.read_sql_query(
        sql=query,
        con=engine,
    )

    print(
        f"Loaded {schema_name}.{table_name}: "
        f"{len(dataframe):,} rows × "
        f"{len(dataframe.columns):,} columns"
    )

    return dataframe


def normalize_string_columns(
    dataframe: pd.DataFrame,
    columns: list[str],
) -> pd.DataFrame:
    """
    Normalize identifiers and grouping columns.

    This performs technical normalization only.
    No finance rules are implemented here.
    """

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

def normalize_identifier_series(
    series: pd.Series,
) -> pd.Series:
    """
    Normalize identifier-like values so equivalent forms match.

    Examples:
        1       -> "1"
        1.0     -> "1"
        "1.0"   -> "1"
        " 1 "   -> "1"

    Non-numeric identifiers remain unchanged.
    """

    text = (
        series.astype("string")
        .str.strip()
        .replace("", pd.NA)
    )

    numeric = pd.to_numeric(
        text,
        errors="coerce",
    )

    whole_number_mask = (
        numeric.notna()
        & numeric.mod(1).eq(0)
    )

    result = text.copy()

    result.loc[whole_number_mask] = (
        numeric.loc[whole_number_mask]
        .astype("Int64")
        .astype("string")
    )

    return result

def prepare_datasets(
    *,
    employee: pd.DataFrame,
    bp: pd.DataFrame,
    sales: pd.DataFrame,
    fx_rates: pd.DataFrame,
    nacs_guarantee: pd.DataFrame,
    ytd_payments: pd.DataFrame,
) -> tuple[
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
    pd.DataFrame,
]:
    """
    Apply technical normalization before metric execution.
    """

    employee = normalize_string_columns(
        employee,
        [
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

    bp = normalize_string_columns(
        bp,
        [
            "sales_group_description",
            "sales_office_description",
        ],
    )

    sales = normalize_string_columns(
        sales,
        [
            "sales_group_description",
            "sales_office_description",
            "profitcentersbudesc",
            "ship_to",
            "gp_flag",
            "low_margin_flag",
        ],
    )

    fx_rates = normalize_string_columns(
        fx_rates,
        [
            "currency_code",
        ],
    )
    nacs_guarantee = normalize_string_columns(
        nacs_guarantee,
        [
            "employee_id",
            "payroll_currency",
        ],
    )

    ytd_payments = normalize_string_columns(
        ytd_payments,
        [
            "employee_id",
            "currency_code",
        ],
    )
    return (
        employee,
        bp,
        sales,
        fx_rates,
        nacs_guarantee,
        ytd_payments,
    )    


# =========================================================
# METRIC EXECUTION
# =========================================================

def build_role_plan(
    *,
    role_id: str,
) -> ResolvedMetricPlan:
    """
    Build one role-specific plan from:

        generic_metrics.yaml
        +
        role_mappings.yaml
    """

    return CalculationConfigLoader.build_plan(
        metric_library_path=SIP_METRICS_PATH,
        role_mapping_path=ROLE_MAPPINGS_PATH,
        role_id=role_id,
    )


def run_role_metrics(
    *,
    role_id: str,
    employee: pd.DataFrame,
    bp: pd.DataFrame,
    sales: pd.DataFrame,
    fx_rates: pd.DataFrame,
    nacs_guarantee: pd.DataFrame,
    ytd_payments: pd.DataFrame,
) -> tuple[pd.DataFrame, ResolvedMetricPlan]:
    """
    Execute all enabled generic metrics and SIP calculations
    for one configured role.

    Runtime finance parameters are not supplied here.
    They come from generic_metrics.yaml through the plan.
    """

    print("\n" + "=" * 100)
    print(f"RUNNING ROLE: {role_id}")
    print("=" * 100)

    plan = build_role_plan(
        role_id=role_id,
    )

    context = CalculationContext(
        employee=employee,
        bp=bp,
        sales=sales,
        fx_rates=fx_rates,
        nacs_guarantee=nacs_guarantee,
        ytd_payments=ytd_payments,
        # Finance/runtime defaults come from YAML.
        fiscal_year=None,
        quarter=None,
        parameters=None,
    )

    metric_engine = MetricEngine()

    result = metric_engine.run(
        plan=plan,
        context=context,
        use_output_names=True,
    )

    result.insert(
        0,
        "calculation_role",
        role_id,
    )

    calculation_quarter = plan.parameters.get(
        "quarter"
    )
    calculation_fiscal_year = plan.parameters.get(
        "fiscal_year"
    )

    result.insert(
        1,
        "calculation_quarter",
        calculation_quarter,
    )

    result.insert(
        2,
        "calculation_fiscal_year",
        calculation_fiscal_year,
    )

    print(
        f"\nCompleted {role_id}: "
        f"{len(result):,} rows × "
        f"{len(result.columns):,} columns"
    )

    print_role_preview(
        dataframe=result,
        plan=plan,
        role_id=role_id,
    )

    return result, plan


def print_role_preview(
    dataframe: pd.DataFrame,
    *,
    plan: ResolvedMetricPlan,
    role_id: str,
) -> None:
    """
    Print canonical identity fields and published metrics.

    Intermediate calculation columns are not included in the
    preview, although they remain available to the engine.
    """

    canonical_preview_columns = [
        "calculation_role",
        "calculation_quarter",
        "calculation_fiscal_year",
        "employee_id",
        "preferred_name",
        "job_profile_for_sip",
        "country",
        "region",
        "bu",
        "sales_office_description",
        "sales_group_description",
        "annual_salary_payroll_currency",
        "payroll_currency",
        "annual_salary_usd",
        "sip_target_pct",
        "sip_eligible_date",
    ]

    published_metric_columns = (
        plan.get_published_output_names()
    )

    preferred_columns = (
        canonical_preview_columns
        + published_metric_columns
    )

    available_columns = [
        column_name
        for column_name in preferred_columns
        if column_name in dataframe.columns
    ]

    print(
        f"\nPublished calculation columns for "
        f"{role_id}:"
    )

    for column_name in published_metric_columns:
        if column_name in dataframe.columns:
            print(f"  - {column_name}")

    if dataframe.empty:
        print(
            "\nNo employees matched this role's "
            "population filter."
        )
        return

    if available_columns:
        print("\nFirst 10 calculated rows:\n")

        print(
            dataframe[
                available_columns
            ]
            .head(10)
            .to_string(index=False)
        )


# =========================================================
# OUTPUT
# =========================================================

def save_parquet(
    dataframe: pd.DataFrame,
    *,
    filename: str,
) -> Path:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIRECTORY / filename
    )

    dataframe.to_parquet(
        output_path,
        index=False,
        engine="pyarrow",
        compression="snappy",
    )

    print(f"Saved Parquet: {output_path}")

    return output_path


def save_csv(
    dataframe: pd.DataFrame,
    *,
    filename: str,
) -> Path:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path = (
        OUTPUT_DIRECTORY / filename
    )

    dataframe.to_csv(
        output_path,
        index=False,
    )

    print(f"Saved CSV: {output_path}")

    return output_path


# =========================================================
# MAIN
# =========================================================

def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    database_engine = create_postgres_engine()

    try:
        employee = load_table(
            database_engine,
            schema_name=EMPLOYEE_SCHEMA,
            table_name=EMPLOYEE_TABLE,
        )

        bp = load_table(
            database_engine,
            schema_name=BP_SCHEMA,
            table_name=BP_TABLE,
        )

        sales = load_table(
            database_engine,
            schema_name=SALES_SCHEMA,
            table_name=SALES_TABLE,
        )

        fx_rates = load_table(
            database_engine,
            schema_name=FX_SCHEMA,
            table_name=FX_TABLE,
        )
        
        nacs_guarantee = load_table(
            database_engine,
            schema_name=NACS_GUARANTEE_SCHEMA,
            table_name=NACS_GUARANTEE_TABLE,
        )

        ytd_payments = load_table(
            database_engine,
            schema_name=YTD_PAYMENTS_SCHEMA,
            table_name=YTD_PAYMENTS_TABLE,
        )
        (
            employee,
            bp,
            sales,
            fx_rates,
            nacs_guarantee,
            ytd_payments
        ) = prepare_datasets(
            employee=employee,
            bp=bp,
            sales=sales,
            fx_rates=fx_rates,
            nacs_guarantee=nacs_guarantee,
            ytd_payments=ytd_payments
        )

        role_ids = load_enabled_role_ids(
            ROLE_MAPPINGS_PATH
        )

        complete_role_results: list[
            pd.DataFrame
        ] = []

        published_role_results: list[
            pd.DataFrame
        ] = []

        for role_id in role_ids:
            role_result, role_plan = run_role_metrics(
                role_id=role_id,
                employee=employee,
                bp=bp,
                sales=sales,
                fx_rates=fx_rates,
                nacs_guarantee=nacs_guarantee,
                ytd_payments=ytd_payments,
            )

            if role_result.empty:
                continue

            # Full engine result, including intermediates.
            save_parquet(
                role_result,
                filename=(
                    f"{role_id}_all_metrics.parquet"
                ),
            )

            complete_role_results.append(
                role_result
            )

            # Final role output containing canonical employee
            # columns plus publish:true metrics only.

            role_sip_output = SIPOutputFormatter.format(
                role_result,
                layout_path=SIP_OUTPUT_LAYOUT_PATH,
            )

            save_csv(
                role_sip_output,
                filename=(
                    f"{role_id}_sip_output.csv"
                ),
            )

            published_role_results.append(
                role_sip_output
            )

        if not complete_role_results:
            print(
                "\nNo rows were calculated for any "
                "enabled role."
            )
            return

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

        all_metrics_parquet_path = save_parquet(
            combined_engine_result,
            filename="all_role_metrics.parquet",
        )

        all_metrics_csv_path = save_csv(
            combined_engine_result,
            filename="all_role_metrics_preview.csv",
        )

        sip_parquet_path = save_parquet(
            combined_sip_output,
            filename="sip_calculations.parquet",
        )

        sip_csv_path = save_csv(
            combined_sip_output,
            filename="sip_calculations.csv",
        )

        print("\n" + "=" * 100)
        print("SIP METRIC ENGINE COMPLETED")
        print("=" * 100)

        print(
            f"Enabled roles       : "
            f"{', '.join(role_ids)}"
        )

        print(
            f"Calculated rows     : "
            f"{len(combined_engine_result):,}"
        )

        print(
            f"Engine columns      : "
            f"{len(combined_engine_result.columns):,}"
        )

        print(
            f"Published columns   : "
            f"{len(combined_sip_output.columns):,}"
        )

        print(
            f"All metrics Parquet : "
            f"{all_metrics_parquet_path}"
        )

        print(
            f"All metrics CSV     : "
            f"{all_metrics_csv_path}"
        )

        print(
            f"SIP output Parquet  : "
            f"{sip_parquet_path}"
        )

        print(
            f"SIP output CSV      : "
            f"{sip_csv_path}"
        )

    finally:
        database_engine.dispose()


if __name__ == "__main__":
    main()
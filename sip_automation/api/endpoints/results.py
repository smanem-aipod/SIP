from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from sip_automation.api.dependencies import get_application
from sip_automation.api.schemas.responses import ResultsResponse
from sip_automation.application import SIPApplication
from sip_automation.core.logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Curated columns shown by default in the results table. Matches the
# headers defined in config/sip_output_layout.yaml. Any column not listed
# here is still returned in the payload and available via "view full row".
_CURATED_COLUMNS = [
    "Employee ID",
    "Preferred Name",
    "Position",
    "Sales Office Description",
    "Sales Group Description",
    "# Months Eligible",
    "YTD Actual in Regional Currency (Revenue)",
    "YTD Actual in Regional Currency (GP/DOP)",
    "BP SG&A",
    "YTD SG&A",
    "YTD SIP Earned",
    "Payroll Currency",
    "YTD SIP Earned (Payroll Cur)",
    "Flag",
]


def _result_file_path(
    application: SIPApplication,
    *,
    run_id: UUID,
    role: str,
) -> Path:
    """
    Resolve the CSV file produced by MetricPipeline for this run/role.

    Mirrors the deterministic output-directory convention used by
    MetricPipeline (project_root/outputs/metric_engine/{run_id}/...).
    """

    project_root = application.config.config_root.parent

    output_directory = (
        project_root
        / "outputs"
        / "metric_engine"
        / str(run_id)
    )

    if role == "all":
        return output_directory / "sip_calculations.csv"

    return output_directory / f"{role}_sip_output.csv"


@router.get(
    "/{run_id}/results",
    response_model=ResultsResponse,
    status_code=status.HTTP_200_OK,
)
def get_results(
    run_id: UUID,
    role: str = Query(
        ...,
        description=(
            "Role ID from the calculations response's enabled_roles, "
            "or 'all' for the combined output."
        ),
    ),
    application: SIPApplication = Depends(get_application),
) -> ResultsResponse:
    """
    Return calculated SIP rows for a completed run as JSON.

    Reads the CSV already written by MetricPipeline for this run/role;
    does not recompute anything.
    """

    result_path = _result_file_path(
        application,
        run_id=run_id,
        role=role,
    )

    if not result_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No results found for run {run_id} and role {role!r}. "
                "Has the calculations stage completed for this run?"
            ),
        )

    try:
        dataframe = pd.read_csv(result_path)

    except Exception as exc:
        logger.exception(
            "api_results_read_failed",
            run_id=str(run_id),
            role=role,
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to read results for run {run_id}.",
        ) from exc

    dataframe = dataframe.where(pd.notna(dataframe), None)

    columns = list(dataframe.columns)

    curated_columns = [
        column
        for column in _CURATED_COLUMNS
        if column in columns
    ]

    return ResultsResponse(
        run_id=run_id,
        role=role,
        row_count=len(dataframe),
        columns=columns,
        curated_columns=curated_columns,
        rows=dataframe.to_dict(orient="records"),
    )


@router.get(
    "/{run_id}/results/download",
    status_code=status.HTTP_200_OK,
)
def download_results(
    run_id: UUID,
    role: str = Query(
        ...,
        description="Role ID or 'all' for the combined output.",
    ),
    application: SIPApplication = Depends(get_application),
) -> FileResponse:
    """
    Download the underlying CSV file for a completed run/role.
    """

    result_path = _result_file_path(
        application,
        run_id=run_id,
        role=role,
    )

    if not result_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"No results found for run {run_id} and role {role!r}."
            ),
        )

    filename = (
        "sip_calculations.csv"
        if role == "all"
        else f"{role}_sip_output.csv"
    )

    return FileResponse(
        path=result_path,
        media_type="text/csv",
        filename=filename,
    )

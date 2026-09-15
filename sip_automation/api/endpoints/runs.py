from __future__ import annotations

import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)

from sip_automation.api.dependencies import get_application
from sip_automation.api.schemas.responses import (CurrentRunResponse, PipelineStageResponse, MetricPipelineResponse, RawLoadResponse, CalculationParametersRequest)
from sip_automation.application import SIPApplication
from sip_automation.core.current_run import CurrentRunStore
from sip_automation.core.logging import get_logger
from sip_automation.core.uploaded_files import UploadedFiles
from sip_automation.core.run_context import RunContext

from sip_automation.core.exceptions import (
    ColumnMappingError,
    DataTypeConversionError,
    DataValidationError,
    PipelineExecutionError,
)

logger = get_logger(__name__)

router = APIRouter()

_ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".xlsb", ".xls"}

_UPLOAD_ROOT = (
    Path(__file__).resolve().parents[3]
    / "storage"
    / "uploads"
)


@router.get(
    "/current",
    response_model=CurrentRunResponse,
    status_code=status.HTTP_200_OK,
)
def get_current_run() -> CurrentRunResponse:
    """
    Return the current active run, if any.

    This pointer is server-side (data/current_run.yaml) rather than only
    living in the browser's sessionStorage, so the last run survives a
    full browser restart, not just a logout within the same tab. It only
    changes when a new run is actually created or its calculations
    complete - navigating the UI does not touch it.
    """

    current_run = CurrentRunStore().get()

    if current_run is None:
        return CurrentRunResponse()

    return CurrentRunResponse(
        run_id=current_run.run_id,
        enabled_roles=current_run.enabled_roles,
        role_row_counts=current_run.role_row_counts,
    )


@router.get(
    "/parameters",
    response_model=dict[str, str | float | int],
    status_code=status.HTTP_200_OK,
)
def get_calculation_parameters(
    application: SIPApplication = Depends(get_application),
) -> dict[str, str | float | int]:
    """
    Return the current finance-controlled SIP parameter defaults used by the
    calculation engine. The admin UI loads this list so it reflects the live
    YAML configuration rather than stale hardcoded JavaScript placeholders.
    """

    return application.config.get_calculation_parameters()


@router.post(
    "",
    response_model=RawLoadResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_run(
    employee_file: UploadFile | None = File(None),
    bp_file: UploadFile | None = File(None),
    sales_file: UploadFile | None = File(None),
    nacs_guarantee_file: UploadFile | None = File(None),
    ytd_payments_file: UploadFile | None = File(None),
    bdm_file: UploadFile | None = File(None),
    application: SIPApplication = Depends(get_application),
) -> RawLoadResponse:

    run_id = uuid4()
    run_directory = (_UPLOAD_ROOT / str(run_id)).resolve()

    provided_files = {
        "employee": employee_file,
        "bp": bp_file,
        "sales": sales_file,
        "nacs_guarantee": nacs_guarantee_file,
        "ytd_payments": ytd_payments_file,
        "bdm": bdm_file,
    }
    provided_files = {
        name: upload
        for name, upload in provided_files.items()
        if upload is not None and upload.filename
    }

    if not provided_files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one source file must be uploaded.",
        )

    try:

        uploaded_paths = {
            logical_name: _save_upload(
                upload,
                run_directory,
                logical_name,
            )
            for logical_name, upload in provided_files.items()
        }

        application.run_raw_loading(
            initiated_by="FastAPI",
            uploaded_files=UploadedFiles(
                files=uploaded_paths,
            ),
            run_id=run_id,
        )

        CurrentRunStore().set_run_id(str(run_id))

        return RawLoadResponse(
            run_id=run_id,
            rows_loaded={},
        )

    except HTTPException:
        shutil.rmtree(run_directory, ignore_errors=True)
        raise

    except Exception as exc:
        logger.exception(
            "api_raw_loading_failed",
            run_id=str(run_id),
            error_type=type(exc).__name__,
        )

        cause = exc.__cause__
        if isinstance(
            cause,
            (
                ColumnMappingError,
                DataTypeConversionError,
                DataValidationError,
                PipelineExecutionError,
            ),
        ):
            shutil.rmtree(run_directory, ignore_errors=True)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(cause),
            ) from exc

        shutil.rmtree(run_directory, ignore_errors=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Raw loading failed for run {run_id}.",
        ) from exc

    finally:
        for upload in provided_files.values():
            upload.file.close()
@router.post(
    "/{run_id}/canonical",
    response_model=PipelineStageResponse,
    status_code=status.HTTP_200_OK,
)
def prepare_canonical_data(
    run_id: UUID,
    application: SIPApplication = Depends(get_application),
) -> PipelineStageResponse:
    """
    Transform raw tables for an existing run into canonical tables.
    """

    context = RunContext.from_config(
        application.config,
        initiated_by="FastAPI",
        run_id=run_id,
    )

    try:
        logger.info(
            "api_canonical_preparation_requested",
            run_id=str(run_id),
        )

        application.run_canonical_preparation(
            context=context,
        )

        logger.info(
            "api_canonical_preparation_completed",
            run_id=str(run_id),
        )

        return PipelineStageResponse(
            run_id=run_id,
            stage="canonical",
            status="completed",
        )

    except (
        ColumnMappingError,
        DataValidationError,
        PipelineExecutionError,
    ) as exc:
        logger.exception(
            "api_canonical_preparation_failed",
            run_id=str(run_id),
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "api_canonical_preparation_failed",
            run_id=str(run_id),
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Canonical preparation failed for run {run_id}.",
        ) from exc
        
@router.post(
    "/{run_id}/calculations",
    response_model=MetricPipelineResponse,
    status_code=status.HTTP_200_OK,
)
def calculate_sip(
    run_id: UUID,
    application: SIPApplication = Depends(get_application),
    params: CalculationParametersRequest | None = Body(default=None, embed=False),
) -> MetricPipelineResponse:
    # Extract non-None parameter overrides from request
    overrides = {}
    if params:
        overrides = {
            k: v for k, v in params.model_dump().items()
            if v is not None
        }
    
    context = RunContext.from_config(
        application.config,
        initiated_by="FastAPI",
        overrides=overrides if overrides else None,
        run_id=run_id,
    )

    try:
        logger.info(
            "api_sip_calculations_requested",
            run_id=str(run_id),
            parameter_overrides=overrides,
        )

        result = application.run_sip_calculations(
            context=context,
        )

        logger.info(
            "api_sip_calculations_completed",
            run_id=str(run_id),
            calculated_row_count=(
                result.calculated_row_count
            ),
            published_row_count=(
                result.published_row_count
            ),
        )

        CurrentRunStore().set_calculation_result(
            run_id=str(run_id),
            enabled_roles=result.enabled_roles,
            role_row_counts=result.role_row_counts,
        )

        return MetricPipelineResponse(
            run_id=run_id,
            calculated_rows=(
                result.calculated_row_count
            ),
            published_rows=(
                result.published_row_count
            ),
            enabled_roles=result.enabled_roles,
            role_row_counts=result.role_row_counts,
            output_directory=str(
                result.output_directory
            ),
            output_files={
                output_name: str(output_path)
                for output_name, output_path
                in result.output_paths.items()
            },
        )

    except Exception as exc:
        logger.exception(
            "api_sip_calculations_failed",
            run_id=str(run_id),
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                f"SIP calculations failed for run "
                f"{run_id}."
            ),
        ) from exc


@router.post(
    "/{run_id}/calculations/apply-parameters",
    response_model=MetricPipelineResponse,
    status_code=status.HTTP_200_OK,
)
def apply_calculation_parameters(
    run_id: UUID,
    application: SIPApplication = Depends(get_application),
    params: CalculationParametersRequest | None = Body(default=None, embed=False),
) -> MetricPipelineResponse:
    """
    Apply new parameter overrides to an existing run's calculations.
    
    This endpoint recalculates SIP metrics with the provided parameter overrides,
    without re-running the entire pipeline. Only calculations are re-executed
    with the new parameters.
    
    Args:
        run_id: The existing run to recalculate
        params: Parameter overrides to apply
        
    Returns:
        Recalculated metrics with the new parameters applied
    """
    
    # Extract non-None parameter overrides from request
    overrides = {}
    if params:
        overrides = {
            k: v for k, v in params.model_dump().items()
            if v is not None
        }
    
    logger.info(
        "api_apply_parameters_debug",
        run_id=str(run_id),
        params_received=params.model_dump() if params else None,
        overrides_extracted=overrides,
    )
    
    context = RunContext.from_config(
        application.config,
        initiated_by="FastAPI",
        overrides=overrides if overrides else None,
        run_id=run_id,
    )

    logger.info(
        "api_apply_parameters_context_created",
        run_id=str(run_id),
        context_parameters=context.parameters,
    )

    try:
        logger.info(
            "api_apply_parameters_requested",
            run_id=str(run_id),
            applied_parameters=overrides,
        )

        result = application.run_sip_calculations(
            context=context,
        )

        logger.info(
            "api_apply_parameters_completed",
            run_id=str(run_id),
            calculated_row_count=(
                result.calculated_row_count
            ),
            applied_parameters=overrides,
        )

        CurrentRunStore().set_calculation_result(
            run_id=str(run_id),
            enabled_roles=result.enabled_roles,
            role_row_counts=result.role_row_counts,
        )

        return MetricPipelineResponse(
            run_id=run_id,
            calculated_rows=(
                result.calculated_row_count
            ),
            published_rows=(
                result.published_row_count
            ),
            enabled_roles=result.enabled_roles,
            role_row_counts=result.role_row_counts,
            output_directory=str(
                result.output_directory
            ),
            output_files={
                output_name: str(output_path)
                for output_name, output_path
                in result.output_paths.items()
            },
        )

    except Exception as exc:
        logger.exception(
            "api_apply_parameters_failed",
            run_id=str(run_id),
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                f"Applying parameters failed for run "
                f"{run_id}."
            ),
        ) from exc

@router.get(
    "/{run_id}/cam-ratios",
    tags=["runs"],
)
def get_cam_ratios(run_id: str) -> dict:
    """
    Compute per-CAM per-division allocation ratios from canonical BP data.

    ratio = cam_bp_target_in_division / total_bp_target_in_division

    Returns list of {cam_id, division_node, allocation_pct_rev, allocation_pct_gp}.
    """
    import pandas as pd

    try:
        application = get_application()
        df = application.container.canonical_repository.read(
            "bp",
            columns=["cam_id", "division_node", "fy26_rev", "fy26_gp"],
            filters={"pipeline_run_id": run_id},
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to read canonical BP data: {exc}",
        ) from exc

    df = df[df["cam_id"].notna()].copy()
    if df.empty:
        return {"ratios": []}

    for col in ("fy26_rev", "fy26_gp"):
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    cam_div = (
        df.groupby(["cam_id", "division_node"], as_index=False)
        .agg(cam_rev=("fy26_rev", "sum"), cam_gp=("fy26_gp", "sum"))
    )
    div_totals = (
        df.groupby("division_node", as_index=False)
        .agg(total_rev=("fy26_rev", "sum"), total_gp=("fy26_gp", "sum"))
    )
    result = cam_div.merge(div_totals, on="division_node", how="left")

    def safe_pct(num, denom):
        return round(float(num / denom * 100), 2) if denom and denom != 0 else None

    ratios = []
    for _, row in result.iterrows():
        ratios.append({
            "cam_id": str(row["cam_id"]),
            "division_node": str(row["division_node"]),
            "allocation_pct_rev": safe_pct(row["cam_rev"], row["total_rev"]),
            "allocation_pct_gp": safe_pct(row["cam_gp"], row["total_gp"]),
        })

    return {"ratios": sorted(ratios, key=lambda r: (r["cam_id"], r["division_node"]))}


def _save_upload(
    upload: UploadFile,
    run_directory: Path,
    logical_table_name: str,
) -> Path:

    filename = Path(upload.filename or "")
    suffix = filename.suffix.lower()

    if suffix not in _ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{logical_table_name} file must be one of "
                f"{sorted(_ALLOWED_SUFFIXES)}."
            ),
        )

    run_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    destination = run_directory / f"{logical_table_name}{suffix}"

    try:
        upload.file.seek(0)

        with destination.open("wb") as output:
            shutil.copyfileobj(
                upload.file,
                output,
            )

    except OSError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unable to save {logical_table_name} upload.",
        ) from exc

    if destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{logical_table_name} file is empty.",
        )

    return destination.resolve()
from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from sip_automation.api.dependencies import get_application
from sip_automation.api.schemas.data_corrections import (
    DataCorrectionFilesResponse,
    DataCorrectionListResponse,
    DataCorrectionRequest,
    DataCorrectionResponse,
)
from sip_automation.core.current_run import CurrentRunStore
from sip_automation.core.data_corrections import (
    ALLOWED_SOURCE_FILES,
    DataCorrection,
    DataCorrectionsStore,
)

# project root = parents[3] of this file (sip_automation/api/endpoints/data_corrections.py)
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
from sip_automation.core.exceptions import (
    PrecomputeExceptionNotFoundError as _NotFoundError,
    PrecomputeExceptionValidationError as _ValidationError,
)
from sip_automation.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _to_response(correction: DataCorrection) -> DataCorrectionResponse:
    return DataCorrectionResponse(**correction.to_dict())


@router.get(
    "/columns/{source_file}",
    status_code=status.HTTP_200_OK,
)
def get_columns(source_file: str) -> dict:
    """Return column names for a source file from the last completed run."""
    if source_file not in ALLOWED_SOURCE_FILES:
        raise HTTPException(status_code=400, detail="Invalid source file.")

    # Use CurrentRunStore with its default path (correctly resolved from core/)
    current = CurrentRunStore().get()
    if not current:
        return {"columns": []}

    try:
        app = get_application()
        repo = app.container.raw_repository
        schema, table = repo.get_target(source_file)
        with repo.engine.connect() as conn:
            df = pd.read_sql(
                text(f'SELECT * FROM "{schema}"."{table}" WHERE pipeline_run_id = :run_id LIMIT 1'),
                conn,
                params={"run_id": current.run_id},
            )
        columns = [c for c in df.columns if c != "pipeline_run_id"]
        return {"columns": columns}
    except Exception:
        return {"columns": []}


@router.get(
    "/files",
    response_model=DataCorrectionFilesResponse,
    status_code=status.HTTP_200_OK,
)
def list_files() -> DataCorrectionFilesResponse:
    """Return allowed source file names and their display labels."""
    return DataCorrectionFilesResponse(files=ALLOWED_SOURCE_FILES)


@router.get(
    "",
    response_model=DataCorrectionListResponse,
    status_code=status.HTTP_200_OK,
)
def list_corrections() -> DataCorrectionListResponse:
    try:
        corrections = DataCorrectionsStore().list()
    except Exception as exc:
        logger.exception("api_data_corrections_list_failed", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load data corrections.",
        ) from exc
    return DataCorrectionListResponse(
        corrections=[_to_response(c) for c in corrections]
    )


@router.post(
    "",
    response_model=DataCorrectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_correction(payload: DataCorrectionRequest) -> DataCorrectionResponse:
    try:
        correction = DataCorrectionsStore().create(
            payload.model_dump(exclude={"changed_by"}),
            changed_by=payload.changed_by,
        )
    except _ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "api_data_correction_create_failed",
            employee_id=payload.employee_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create data correction.",
        ) from exc
    return _to_response(correction)


@router.put(
    "/{correction_id}",
    response_model=DataCorrectionResponse,
    status_code=status.HTTP_200_OK,
)
def update_correction(
    correction_id: str, payload: DataCorrectionRequest
) -> DataCorrectionResponse:
    try:
        correction = DataCorrectionsStore().update(
            correction_id,
            payload.model_dump(exclude={"changed_by"}),
            changed_by=payload.changed_by,
        )
    except _NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except _ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "api_data_correction_update_failed",
            correction_id=correction_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update data correction.",
        ) from exc
    return _to_response(correction)


@router.delete("/{correction_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_correction(correction_id: str, changed_by: str | None = None) -> None:
    try:
        DataCorrectionsStore().delete(correction_id, changed_by=changed_by)
    except _NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "api_data_correction_delete_failed",
            correction_id=correction_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete data correction.",
        ) from exc

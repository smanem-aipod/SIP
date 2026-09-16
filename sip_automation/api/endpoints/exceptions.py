from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import APIRouter, File, HTTPException, UploadFile, status

from sip_automation.api.schemas.exceptions import (
    PrecomputeExceptionCategoriesResponse,
    PrecomputeExceptionListResponse,
    PrecomputeExceptionRequest,
    PrecomputeExceptionResponse,
    PrecomputeExceptionUploadResponse,
    PrecomputeExceptionUploadRowError,
)
from sip_automation.core.exceptions import (
    PrecomputeExceptionNotFoundError,
    PrecomputeExceptionValidationError,
)
from sip_automation.core.logging import get_logger
from sip_automation.core.precompute_exceptions import (
    EXCEPTION_UPLOAD_FIELDS,
    PRECOMPUTE_EXCEPTION_CATEGORIES,
    PrecomputeException,
    PrecomputeExceptionsStore,
)

logger = get_logger(__name__)

router = APIRouter()

_ALLOWED_UPLOAD_SUFFIXES = {".xlsx", ".xls", ".csv"}

# Wide upload format: one row per employee, one column per field (same
# field names as the single-row Add Exception modal / PrecomputeExceptionRequest).
# Admins fill in only the columns that apply to a given employee and leave
# the rest blank.
_UPLOAD_COLUMNS = EXCEPTION_UPLOAD_FIELDS


def _normalize_header(header: Any) -> str:
    return (
        str(header)
        .strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )


def _clean_cell(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, float) and pd.isna(value):
        return None

    if isinstance(value, str) and not value.strip():
        return None

    return value


def _read_upload_dataframe(upload: UploadFile) -> pd.DataFrame:
    filename = Path(upload.filename or "")
    suffix = filename.suffix.lower()

    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Upload file must be one of "
                f"{sorted(_ALLOWED_UPLOAD_SUFFIXES)}."
            ),
        )

    upload.file.seek(0)
    content = upload.file.read()

    try:
        if suffix == ".csv":
            dataframe = pd.read_csv(io.BytesIO(content))
        else:
            dataframe = pd.read_excel(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Unable to read upload file: {exc}",
        ) from exc

    normalized_columns = {
        column: _normalize_header(column)
        for column in dataframe.columns
    }

    dataframe = dataframe.rename(columns=normalized_columns)
    recognized_columns = [
        column
        for column in dataframe.columns
        if column in _UPLOAD_COLUMNS
    ]

    return dataframe[recognized_columns]


def _parse_upload_rows(
    upload: UploadFile,
) -> list[dict[str, Any]]:
    """
    Parse the wide-format upload (one row per employee, one column per
    field) into payload dicts that PrecomputeExceptionsStore.replace_all()
    understands. Unrecognized columns are ignored; blank cells become None
    so admins can leave any field that doesn't apply to a given employee
    empty.
    """

    dataframe = _read_upload_dataframe(upload)
    records = dataframe.to_dict(orient="records")

    payloads: list[dict[str, Any]] = []

    for row_number, record in enumerate(records, start=1):
        payload: dict[str, Any] = {"_row_number": row_number}

        for field in EXCEPTION_UPLOAD_FIELDS:
            payload[field] = _clean_cell(record.get(field))

        payloads.append(payload)

    return payloads


def _to_response(
    exception: PrecomputeException,
) -> PrecomputeExceptionResponse:
    return PrecomputeExceptionResponse(**exception.to_dict())


@router.get(
    "/categories",
    response_model=PrecomputeExceptionCategoriesResponse,
    status_code=status.HTTP_200_OK,
)
def list_categories() -> PrecomputeExceptionCategoriesResponse:
    """
    Preset category labels for the admin UI dropdown. Custom, free-text
    categories are still accepted by the create/update endpoints.
    """

    return PrecomputeExceptionCategoriesResponse(
        categories=list(PRECOMPUTE_EXCEPTION_CATEGORIES)
    )


@router.get(
    "",
    response_model=PrecomputeExceptionListResponse,
    status_code=status.HTTP_200_OK,
)
def list_exceptions() -> PrecomputeExceptionListResponse:
    try:
        exceptions = PrecomputeExceptionsStore().list()

    except Exception as exc:
        logger.exception(
            "api_precompute_exceptions_list_failed",
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load precompute exceptions.",
        ) from exc

    return PrecomputeExceptionListResponse(
        exceptions=[
            _to_response(exception)
            for exception in exceptions
        ]
    )


@router.post(
    "",
    response_model=PrecomputeExceptionResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_exception(
    payload: PrecomputeExceptionRequest,
) -> PrecomputeExceptionResponse:
    try:
        exception = PrecomputeExceptionsStore().create(
            payload.model_dump(exclude={"changed_by"}),
            changed_by=payload.changed_by,
        )

    except PrecomputeExceptionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "api_precompute_exception_create_failed",
            employee_id=payload.employee_id,
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create precompute exception.",
        ) from exc

    return _to_response(exception)


@router.post(
    "/upload",
    response_model=PrecomputeExceptionUploadResponse,
    status_code=status.HTTP_200_OK,
)
def upload_exceptions(
    file: UploadFile = File(...),
    changed_by: str | None = None,
) -> PrecomputeExceptionUploadResponse:
    """
    Bulk-replace the entire precompute exceptions list from an uploaded
    Excel/CSV file (wide format: one row per employee, one column per
    field - same fields as the single-row Add Exception modal). Admins
    leave any column blank that doesn't apply to a given employee. Rows
    that fail validation are skipped and reported (partial success); if
    every row fails, nothing is changed on disk.
    """

    try:
        payloads = _parse_upload_rows(file)
    finally:
        file.file.close()

    if not payloads:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Upload file has no data rows.",
        )

    try:
        saved, errors = PrecomputeExceptionsStore().replace_all(
            payloads,
            changed_by=changed_by,
        )

    except Exception as exc:
        logger.exception(
            "api_precompute_exceptions_upload_failed",
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to process precompute exceptions upload.",
        ) from exc

    if not saved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "No valid rows found in upload; existing exceptions "
                "were not changed. Errors: "
                + "; ".join(
                    f"row {row_number}: {message}"
                    for row_number, _, message in errors
                )
            ),
        )

    return PrecomputeExceptionUploadResponse(
        total_rows=len(payloads),
        saved_count=len(saved),
        error_count=len(errors),
        errors=[
            PrecomputeExceptionUploadRowError(
                row_number=row_number,
                employee_id=employee_id,
                error=message,
            )
            for row_number, employee_id, message in errors
        ],
    )


@router.put(
    "/{exception_id}",
    response_model=PrecomputeExceptionResponse,
    status_code=status.HTTP_200_OK,
)
def update_exception(
    exception_id: str,
    payload: PrecomputeExceptionRequest,
) -> PrecomputeExceptionResponse:
    try:
        exception = PrecomputeExceptionsStore().update(
            exception_id,
            payload.model_dump(exclude={"changed_by"}),
            changed_by=payload.changed_by,
        )

    except PrecomputeExceptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except PrecomputeExceptionValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "api_precompute_exception_update_failed",
            exception_id=exception_id,
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update precompute exception.",
        ) from exc

    return _to_response(exception)


@router.delete(
    "/{exception_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_exception(
    exception_id: str,
    changed_by: str | None = None,
) -> None:
    try:
        PrecomputeExceptionsStore().delete(
            exception_id,
            changed_by=changed_by,
        )

    except PrecomputeExceptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except Exception as exc:
        logger.exception(
            "api_precompute_exception_delete_failed",
            exception_id=exception_id,
            error_type=type(exc).__name__,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete precompute exception.",
        ) from exc

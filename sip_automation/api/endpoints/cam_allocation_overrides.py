from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from sip_automation.api.schemas.cam_allocation_overrides import (
    CAMAllocationOverrideListResponse,
    CAMAllocationOverrideRequest,
    CAMAllocationOverrideResponse,
)
from sip_automation.core.cam_allocation_overrides import (
    CAMAllocationOverride,
    CAMAllocationOverridesStore,
)
from sip_automation.core.exceptions import (
    PrecomputeExceptionNotFoundError as _NotFoundError,
    PrecomputeExceptionValidationError as _ValidationError,
)
from sip_automation.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter()


def _to_response(override: CAMAllocationOverride) -> CAMAllocationOverrideResponse:
    return CAMAllocationOverrideResponse(**override.to_dict())


@router.get(
    "",
    response_model=CAMAllocationOverrideListResponse,
    status_code=status.HTTP_200_OK,
)
def list_overrides() -> CAMAllocationOverrideListResponse:
    try:
        overrides = CAMAllocationOverridesStore().list()
    except Exception as exc:
        logger.exception("api_cam_overrides_list_failed", error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to load CAM allocation overrides.",
        ) from exc
    return CAMAllocationOverrideListResponse(
        overrides=[_to_response(o) for o in overrides]
    )


@router.post(
    "",
    response_model=CAMAllocationOverrideResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_override(payload: CAMAllocationOverrideRequest) -> CAMAllocationOverrideResponse:
    try:
        override = CAMAllocationOverridesStore().create(
            payload.model_dump(exclude={"changed_by"}),
            changed_by=payload.changed_by,
        )
    except _ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "api_cam_override_create_failed",
            cam_id=payload.cam_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create CAM allocation override.",
        ) from exc
    return _to_response(override)


@router.put(
    "/{override_id}",
    response_model=CAMAllocationOverrideResponse,
    status_code=status.HTTP_200_OK,
)
def update_override(
    override_id: str, payload: CAMAllocationOverrideRequest
) -> CAMAllocationOverrideResponse:
    try:
        override = CAMAllocationOverridesStore().update(
            override_id,
            payload.model_dump(exclude={"changed_by"}),
            changed_by=payload.changed_by,
        )
    except _NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except _ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "api_cam_override_update_failed",
            override_id=override_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update CAM allocation override.",
        ) from exc
    return _to_response(override)


@router.delete("/{override_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_override(override_id: str, changed_by: str | None = None) -> None:
    try:
        CAMAllocationOverridesStore().delete(override_id, changed_by=changed_by)
    except _NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "api_cam_override_delete_failed",
            override_id=override_id,
            error_type=type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete CAM allocation override.",
        ) from exc

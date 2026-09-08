from fastapi import APIRouter

from sip_automation.api.endpoints.cam_allocation_overrides import (
    router as cam_allocation_router,
)
from sip_automation.api.endpoints.data_corrections import (
    router as data_corrections_router,
)
from sip_automation.api.endpoints.exceptions import (
    router as exceptions_router,
)
from sip_automation.api.endpoints.hr_reconciliation import (
    router as hr_reconciliation_router,
)
from sip_automation.api.endpoints.results import router as results_router
from sip_automation.api.endpoints.runs import router as runs_router


api_router = APIRouter(prefix="/api/v1")
api_router.include_router(runs_router, prefix="/runs", tags=["runs"])
api_router.include_router(results_router, prefix="/runs", tags=["results"])
api_router.include_router(
    exceptions_router,
    prefix="/exceptions",
    tags=["exceptions"],
)
api_router.include_router(
    hr_reconciliation_router,
    prefix="/hr-reconciliation",
    tags=["hr-reconciliation"],
)
api_router.include_router(
    data_corrections_router,
    prefix="/data-corrections",
    tags=["data-corrections"],
)
api_router.include_router(
    cam_allocation_router,
    prefix="/cam-allocations",
    tags=["cam-allocations"],
)

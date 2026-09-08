from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from sip_automation.api.dependencies import get_application
from sip_automation.api.router import api_router
from sip_automation.api.schemas.responses import HealthResponse


app = FastAPI(
    title="SIP Automation API",
    version="0.1.0",
)
app.include_router(api_router)

_STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount(
    "/ui",
    StaticFiles(directory=_STATIC_DIR, html=True),
    name="ui",
)


@app.middleware("http")
async def _no_cache_static_ui(request, call_next):
    # The UI (index.html/app.js/styles.css) changes often during development.
    # Without this, browsers can heuristically cache these files (no
    # Cache-Control header is set by default), leading to stale JS/CSS being
    # served alongside a fresher HTML file - a mismatch that can look like a
    # UI bug (e.g. two screens appearing to overlap) but is really just an
    # old script running against new markup. Forcing revalidation on every
    # request avoids that class of issue.
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/", include_in_schema=False)
def redirect_to_ui() -> RedirectResponse:
    return RedirectResponse(url="/ui/")



@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse()


@app.on_event("shutdown")
def shutdown_application() -> None:
    if get_application.cache_info().currsize:
        get_application().close()
        get_application.cache_clear()

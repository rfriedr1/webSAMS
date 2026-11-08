"""EA check routes: the Lab → EA Checks page, logging a check, voiding one.

Thin dispatchers over `ea_checks.EaCheckLog`. Logging is posted from the
entry strip, which appears on both this page and Lab → Graphitization, so
the POST redirects back to the page it came from (`next`).
"""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, Query, Request

from sams_web.access import Permission, guarded
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.ea_checks import EaCheckLog
from sams_web.routers.pages_shared import templates
from sams_web.services import SamsService

router = APIRouter()

DEFAULT_RETURN = "/lab/ea-checks"


def safe_return_url(raw: str | None, default: str = DEFAULT_RETURN) -> str:
    """Only same-site paths: refuses `//host`, `http://…` and anything odd."""
    value = (raw or "").strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return default
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return default
    return value


_TRANSIENT_PARAMS = {
    "ea_check_notice", "ea_check_error", "signoff_notice", "signoff_error",
    "graph_saved", "graph_notice", "graph_batch_notice", "graph_batch_error", "graph_batch_saved",
}


def current_return_url(request: Request) -> str:
    """This page's URL without one-shot notice params, for the strip's `next`."""
    kept = [(k, v) for k, v in request.query_params.multi_items() if k not in _TRANSIENT_PARAMS]
    return request.url.path + (f"?{urlencode(kept)}" if kept else "")


def ea_strip_context(service: SamsService, request: Request, return_url: str | None = None) -> dict:
    """What `_ea_check_strip.html` needs, for any page that includes it.
    Pass `return_url` when rendering from a POST (its own URL is not a page)."""
    log = EaCheckLog(service)
    strip = log.strip_view()
    return {
        "ea_strip": strip,
        "ea_return_url": return_url or current_return_url(request),
        "ea_check_error": request.query_params.get("ea_check_error", "").strip(),
    }


def redirect_with(url: str, params: dict[str, str], fragment: str = "") -> RedirectResponse:
    base, _, existing_fragment = url.partition("#")
    separator = "&" if "?" in base else "?"
    target = f"{base}{separator}{urlencode(params)}"
    anchor = fragment or existing_fragment
    return RedirectResponse(f"{target}#{anchor}" if anchor else target, status_code=303)


@router.get("/lab/ea-checks")
def ea_checks_page(
    request: Request,
    ea: str = Query(default=""),
    period: str = Query(default="unsigned"),
    ea_check_error: str = Query(default=""),
    signoff_error: str = Query(default=""),
    service: SamsService = Depends(get_service),
):
    log = EaCheckLog(service)
    context = log.page_view(ea=ea.strip() or None, period=period.strip())
    context.update(
        {
            "request": request,
            "title": "EA Checks",
            "ea_check_error": ea_check_error.strip(),
            "signoff_error": signoff_error.strip(),
            "ea_return_url": current_return_url(request),
        }
    )
    return templates.TemplateResponse(request, "ea_checks.html", context)


@router.post("/lab/ea-checks", dependencies=guarded(Permission.EDIT_RECORDS))
async def ea_check_record(request: Request, service: SamsService = Depends(get_service)):
    form = await request.form()
    submitted = {key: str(form.get(key) or "") for key in form.keys()}
    next_url = safe_return_url(submitted.get("next"))
    outcome = EaCheckLog(service).record(submitted)
    if outcome.success:
        return redirect_with(next_url, {"ea_check_notice": outcome.message}, "ea-check-strip")
    params = {"ea_check_error": outcome.error or "Could not log the check."}
    return redirect_with(next_url, params, "ea-check-strip")


@router.post("/lab/ea-checks/{check_id}/void", dependencies=guarded(Permission.EDIT_RECORDS))
async def ea_check_void(check_id: int, request: Request, service: SamsService = Depends(get_service)):
    form = await request.form()
    next_url = safe_return_url(str(form.get("next") or ""))
    outcome = EaCheckLog(service).void(
        check_id, reason=str(form.get("reason") or ""), by=str(form.get("by") or "")
    )
    if outcome.success:
        return redirect_with(next_url, {"ea_check_notice": outcome.message}, "ea-history")
    return redirect_with(next_url, {"ea_check_error": outcome.error or "Could not void the check."}, "ea-history")

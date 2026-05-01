"""Magic Nav route handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.magic_nav import (
    INVALID_MAGIC_NAV_MESSAGE,
    append_magic_feedback,
    nav_exists,
    nav_not_found_message,
    resolve_magic_identifier,
)
from sams_web.services import SamsService

router = APIRouter()


@router.get("/magic/open")
@router.get("/samples/open")
def magic_identifier_lookup(
    magic_identifier: str | None = Query(default=None),
    sample_nr: str | None = Query(default=None),
    next: str | None = Query(default=None),
    service: SamsService = Depends(get_service),
):
    fallback = next if next and next.startswith("/") else "/search"
    raw = (magic_identifier or sample_nr or "").strip()
    if not raw:
        return RedirectResponse(url=fallback, status_code=303)

    nav = resolve_magic_identifier(raw)
    if nav is None:
        return RedirectResponse(
            url=append_magic_feedback(fallback, raw, INVALID_MAGIC_NAV_MESSAGE),
            status_code=303,
        )

    if not nav_exists(nav, service):
        return RedirectResponse(
            url=append_magic_feedback(fallback, raw, nav_not_found_message(nav)),
            status_code=303,
        )

    return RedirectResponse(url=nav.target, status_code=303)

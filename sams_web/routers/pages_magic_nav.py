"""Magic Nav route handlers."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.routers.pages_shared import append_magic_feedback, resolve_magic_identifier
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

    resolved = resolve_magic_identifier(raw)
    if resolved is None:
        return RedirectResponse(
            url=append_magic_feedback(
                fallback,
                entered_value=raw,
                error_message=(
                    "Invalid Magic Nav ID. Use 123, 45230.1, 45230.1.1, "
                    "pr123, usr210, /prep, /graph, or /ana."
                ),
            ),
            status_code=303,
        )

    exists = resolved.kind == "command"
    if resolved.kind == "sample" and resolved.identifier is not None:
        exists = service.sample_exists(resolved.identifier)
    elif resolved.kind == "preparation" and resolved.sample_nr is not None and resolved.prep_nr is not None:
        exists = service.preparation_exists(resolved.sample_nr, resolved.prep_nr)
    elif (
        resolved.kind == "target"
        and resolved.sample_nr is not None
        and resolved.prep_nr is not None
        and resolved.target_nr is not None
    ):
        exists = service.target_exists(resolved.sample_nr, resolved.prep_nr, resolved.target_nr)
    elif resolved.kind == "project" and resolved.identifier is not None:
        exists = service.project_exists(resolved.identifier)
    elif resolved.kind == "user" and resolved.identifier is not None:
        exists = service.user_exists(resolved.identifier)

    if not exists:
        if resolved.kind == "preparation" and resolved.sample_nr is not None and resolved.prep_nr is not None:
            not_found_message = f"Preparation {resolved.sample_nr}.{resolved.prep_nr} was not found."
        elif (
            resolved.kind == "target"
            and resolved.sample_nr is not None
            and resolved.prep_nr is not None
            and resolved.target_nr is not None
        ):
            not_found_message = (
                f"Target {resolved.sample_nr}.{resolved.prep_nr}.{resolved.target_nr} was not found."
            )
        else:
            not_found_message = f"{resolved.kind.title()} #{int(resolved.identifier or 0)} was not found."
        return RedirectResponse(
            url=append_magic_feedback(
                fallback,
                entered_value=raw,
                error_message=not_found_message,
            ),
            status_code=303,
        )
    return RedirectResponse(url=resolved.target, status_code=303)

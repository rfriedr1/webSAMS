"""Target detail routes."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from sams_web import target_swap
from sams_web.access import Permission, guarded

from sams_web.dependencies import get_service
from sams_web.detail_page import EditFormState, NavCursor, build_detail_page_context
from sams_web.routers.pages_shared import LAST_SAMPLE_COOKIE, logger, resolve_jump_redirect_url, templates
from sams_web.services import SamsService
from sams_web.viewmodels.detail_sections_sample_lab import TARGET_DETAIL_PAGE

router = APIRouter()


def _target_extra_keys(
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    data: dict[str, object],
) -> dict[str, object]:
    """Page-specific extras: related entities and prep-options for the
    +Target form. Field values and warnings come from
    `TARGET_DETAIL_PAGE.sections_builder` / `.warnings_builder`."""
    return {
        "sample": data["sample"],
        "project": data["project"],
        "user": data["user"],
        "preparation": data["preparation"],
        "target_prep_options": data.get("preparations", []),
        "sample_nr": sample_nr,
        "prep_nr": prep_nr,
        "target_nr": target_nr,
    }


def _target_cursor(data: dict[str, object]) -> NavCursor:
    return NavCursor(
        previous_nr=data["previous_target_nr"],
        next_nr=data["next_target_nr"],
        count=data["target_count"],
        max_nr=data["max_target_nr"],
    )


@router.get("/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}")
def target_detail_page(
    request: Request,
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    jump_target: str | None = Query(default=None),
    saved: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_target_details(sample_nr, prep_nr, target_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Target not found")

    def target_url(resolved_target_nr: int) -> str:
        return f"/samples/{sample_nr}/preparations/{prep_nr}/targets/{resolved_target_nr}"

    if jump_target is not None:
        fallback_url = target_url(target_nr)
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_target,
            current_id=target_nr,
            max_id=int(data.get("max_target_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=target_url,
            exists_fn=lambda jump_id: service.target_exists(sample_nr, prep_nr, jump_id),
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    response = templates.TemplateResponse(request, "target_detail.html",
        build_detail_page_context(
            request,
            TARGET_DETAIL_PAGE,
            entity=data["target"],
            cursor=_target_cursor(data),
            edit_state=EditFormState(saved=saved),
            service=service,
            lab_warning_thresholds=service.get_lab_warning_thresholds(),
            extra=_target_extra_keys(sample_nr, prep_nr, target_nr, data),
        ),
    )
    response.set_cookie(
        key=LAST_SAMPLE_COOKIE,
        value=str(sample_nr),
        path="/",
        samesite="lax",
    )
    return response


@router.post("/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}/save", dependencies=guarded(Permission.EDIT_RECORDS))
async def save_target_detail_page(
    request: Request,
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    service: SamsService = Depends(get_service),
):
    data = service.get_target_details(sample_nr, prep_nr, target_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Target not found")

    raw_form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key, value in raw_form.items():
        if not key.startswith("target__"):
            continue
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    saved, field_errors, save_error = service.update_target_detail(
        sample_nr, prep_nr, target_nr, submitted_fields
    )
    if saved:
        response = RedirectResponse(
            url=f"/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}?saved=true",
            status_code=303,
        )
        response.set_cookie(
            key=LAST_SAMPLE_COOKIE,
            value=str(sample_nr),
            path="/",
            samesite="lax",
        )
        return response

    response = templates.TemplateResponse(request, "target_detail.html",
        build_detail_page_context(
            request,
            TARGET_DETAIL_PAGE,
            entity=data["target"],
            cursor=_target_cursor(data),
            edit_state=EditFormState(
                saved=False,
                save_error=save_error,
                field_errors=field_errors,
                form_values=submitted_fields,
            ),
            service=service,
            lab_warning_thresholds=service.get_lab_warning_thresholds(),
            extra=_target_extra_keys(sample_nr, prep_nr, target_nr, data),
        ),
        status_code=422,
    )
    response.set_cookie(
        key=LAST_SAMPLE_COOKIE,
        value=str(sample_nr),
        path="/",
        samesite="lax",
    )
    return response


# ---- Swap target info (ADR-0008) ------------------------------------------


@router.get(
    "/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}/swap/preview",
    dependencies=guarded(Permission.EDIT_RECORDS),
)
def target_swap_preview(
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    with_sample: int = Query(...),
    with_prep: int = Query(default=1),
    with_target: int = Query(default=1),
    service: SamsService = Depends(get_service),
):
    """Both targets' values per group, for the swap dialog (JSON)."""
    try:
        payload = target_swap.plan(
            service, (sample_nr, prep_nr, target_nr), (with_sample, with_prep, with_target)
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(payload)


@router.post(
    "/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}/swap",
    dependencies=guarded(Permission.EDIT_RECORDS),
)
def target_swap_run(
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    with_sample: int = Form(...),
    with_prep: int = Form(...),
    with_target: int = Form(...),
    groups: list[str] = Form(default=[]),
    service: SamsService = Depends(get_service),
):
    first = (sample_nr, prep_nr, target_nr)
    second = (with_sample, with_prep, with_target)
    back = target_swap.target_href(first)
    try:
        notice = target_swap.apply(service, first, second, target_swap.parse_groups(groups))
    except ValueError as exc:
        return RedirectResponse(url=f"{back}?{urlencode({'action_error': str(exc)})}", status_code=303)
    logger.info(
        "Target swap %s <-> %s: %s",
        target_swap.key_text(first), target_swap.key_text(second), ", ".join(groups),
    )
    return RedirectResponse(url=f"{back}?{urlencode({'action_notice': notice})}", status_code=303)

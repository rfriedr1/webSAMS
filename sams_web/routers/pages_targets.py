"""Target detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.detail_page import EditFormState, NavCursor, build_detail_page_context
from sams_web.routers.pages_shared import LAST_SAMPLE_COOKIE, resolve_jump_redirect_url, templates
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
    +Target form. Headline display values + warnings come from
    `TARGET_DETAIL_PAGE.headline_builder` / `.warnings_builder`."""
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

    response = templates.TemplateResponse(
        "target_detail.html",
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


@router.post("/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}/save")
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

    response = templates.TemplateResponse(
        "target_detail.html",
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
                edit_initial_mode="editing",
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

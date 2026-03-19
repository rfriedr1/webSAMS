"""Target detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.routers.detail_contexts import build_target_detail_context
from sams_web.routers.pages_shared import LAST_SAMPLE_COOKIE, resolve_jump_redirect_url, templates
from sams_web.services import SamsService

router = APIRouter()


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
        build_target_detail_context(
            request,
            sample_nr=sample_nr,
            prep_nr=prep_nr,
            target_nr=target_nr,
            data=data,
            saved=saved,
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

    saved, field_errors, save_error = service.update_target_detail(sample_nr, prep_nr, target_nr, submitted_fields)
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
        build_target_detail_context(
            request,
            sample_nr=sample_nr,
            prep_nr=prep_nr,
            target_nr=target_nr,
            data=data,
            saved=False,
            save_error=save_error,
            target_field_errors=field_errors,
            target_form_values=submitted_fields,
            target_edit_initial_mode="editing",
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

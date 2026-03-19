"""Preparation detail routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.routers.detail_contexts import build_preparation_detail_context
from sams_web.routers.pages_shared import LAST_SAMPLE_COOKIE, resolve_jump_redirect_url, templates
from sams_web.services import SamsService

router = APIRouter()


@router.get("/samples/{sample_nr}/preparations/{prep_nr}")
def preparation_detail_page(
    request: Request,
    sample_nr: int,
    prep_nr: int,
    jump_prep: str | None = Query(default=None),
    saved: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_preparation_details(sample_nr, prep_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Preparation not found")

    if jump_prep is not None:
        fallback_url = f"/samples/{sample_nr}/preparations/{prep_nr}"
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_prep,
            current_id=prep_nr,
            max_id=int(data.get("max_prep_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=lambda jump_id: f"/samples/{sample_nr}/preparations/{jump_id}",
            exists_fn=lambda jump_id: service.preparation_exists(sample_nr, jump_id),
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    response = templates.TemplateResponse(
        "preparation_detail.html",
        build_preparation_detail_context(
            request,
            data=data,
            service=service,
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


@router.post("/samples/{sample_nr}/preparations/{prep_nr}/save")
async def save_preparation_detail_page(
    request: Request,
    sample_nr: int,
    prep_nr: int,
    service: SamsService = Depends(get_service),
):
    data = service.get_preparation_details(sample_nr, prep_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Preparation not found")

    raw_form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key, value in raw_form.items():
        if not key.startswith("preparation__"):
            continue
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    saved, field_errors, save_error = service.update_preparation_detail(sample_nr, prep_nr, submitted_fields)
    if saved:
        response = RedirectResponse(
            url=f"/samples/{sample_nr}/preparations/{prep_nr}?saved=true",
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
        "preparation_detail.html",
        build_preparation_detail_context(
            request,
            data=data,
            service=service,
            saved=False,
            save_error=save_error,
            preparation_field_errors=field_errors,
            preparation_form_values=submitted_fields,
            preparation_edit_initial_mode="editing",
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

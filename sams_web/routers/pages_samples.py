"""Sample list and detail routes."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.routers.detail_contexts import build_sample_creation_notice, build_sample_detail_context
from sams_web.routers.pages_shared import LAST_SAMPLE_COOKIE, resolve_jump_redirect_url, templates
from sams_web.services import SamsService

router = APIRouter()


@router.get("/samples")
def samples_landing_page(
    request: Request,
    service: SamsService = Depends(get_service),
):
    preferred_sample_nr: int | None = None
    cookie_value = (request.cookies.get(LAST_SAMPLE_COOKIE) or "").strip()
    if re.fullmatch(r"\d+", cookie_value):
        preferred_sample_nr = int(cookie_value)

    resolved_sample_nr = service.resolve_samples_landing_sample_nr(preferred_sample_nr=preferred_sample_nr)
    if resolved_sample_nr is None:
        return RedirectResponse(url="/search?context=samples", status_code=303)
    return RedirectResponse(url=f"/samples/{resolved_sample_nr}", status_code=303)


@router.post("/samples/new")
def create_sample_form(
    project_nr: int = Form(...),
    user_label: str = Form(...),
    user_label_nr: str | None = Form(default=None),
    user_desc1: str | None = Form(default=None),
    user_desc2: str | None = Form(default=None),
    type: str | None = Form(default=None),
    material: str | None = Form(default=None),
    fraction: str | None = Form(default=None),
    service: SamsService = Depends(get_service),
):
    sample = service.create_sample(
        {
            "project_nr": project_nr,
            "user_label": user_label,
            "user_label_nr": user_label_nr,
            "user_desc1": user_desc1,
            "user_desc2": user_desc2,
            "type": type,
            "material": material,
            "fraction": fraction,
        },
        with_blank_records=True,
    )
    return RedirectResponse(url=f"/samples/{sample.sample_nr}", status_code=303)


@router.get("/samples/{sample_nr}")
def sample_detail_page(
    request: Request,
    sample_nr: int,
    prep: int | None = Query(default=None),
    target: int | None = Query(default=None),
    jump_sample: str | None = Query(default=None),
    saved: bool = Query(default=False),
    created: str | None = Query(default=None),
    created_prep: int | None = Query(default=None),
    created_target: int | None = Query(default=None),
    service: SamsService = Depends(get_service),
):
    if prep is not None and target is not None:
        return RedirectResponse(
            url=f"/samples/{sample_nr}/preparations/{prep}/targets/{target}",
            status_code=303,
        )
    if prep is not None:
        return RedirectResponse(
            url=f"/samples/{sample_nr}/preparations/{prep}",
            status_code=303,
        )

    overview = service.get_sample_overview(sample_nr)
    if overview is None:
        raise HTTPException(status_code=404, detail="Sample not found")

    if jump_sample is not None:
        fallback_url = f"/samples/{sample_nr}"
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_sample,
            current_id=sample_nr,
            max_id=int(overview.get("max_sample_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=lambda jump_id: f"/samples/{jump_id}",
            exists_fn=service.sample_exists,
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    response = templates.TemplateResponse(
        "sample_detail.html",
        build_sample_detail_context(
            request,
            overview=overview,
            service=service,
            saved=saved,
            creation_notice=build_sample_creation_notice(
                created=created,
                created_prep=created_prep,
                created_target=created_target,
            ),
        ),
    )
    response.set_cookie(
        key=LAST_SAMPLE_COOKIE,
        value=str(sample_nr),
        path="/",
        samesite="lax",
    )
    return response


@router.post("/samples/{sample_nr}/add-preparation")
def create_new_preparation_for_sample(
    sample_nr: int,
    return_to: str | None = Form(default=None),
    service: SamsService = Depends(get_service),
):
    try:
        prep_nr, target_nr = service.create_next_prep_for_sample(sample_nr)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (return_to or "").strip().lower() == "preparation":
        return RedirectResponse(
            url=f"/samples/{sample_nr}/preparations/{prep_nr}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/samples/{sample_nr}?created=prep&created_prep={prep_nr}&created_target={target_nr}",
        status_code=303,
    )


@router.post("/samples/{sample_nr}/add-target")
def create_new_target_for_sample_prep(
    sample_nr: int,
    prep_nr: int = Form(...),
    return_to: str | None = Form(default=None),
    service: SamsService = Depends(get_service),
):
    try:
        target_nr = service.create_next_target_for_sample_prep(sample_nr, prep_nr)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if (return_to or "").strip().lower() == "target":
        return RedirectResponse(
            url=f"/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}",
            status_code=303,
        )
    return RedirectResponse(
        url=f"/samples/{sample_nr}?created=target&created_prep={prep_nr}&created_target={target_nr}",
        status_code=303,
    )


@router.post("/samples/{sample_nr}/save")
async def save_sample_detail_page(
    request: Request,
    sample_nr: int,
    service: SamsService = Depends(get_service),
):
    overview = service.get_sample_overview(sample_nr)
    if overview is None:
        raise HTTPException(status_code=404, detail="Sample not found")

    raw_form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key, value in raw_form.items():
        if not key.startswith("sample__"):
            continue
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    saved, field_errors, save_error = service.update_sample_detail(sample_nr, submitted_fields)
    if saved:
        response = RedirectResponse(url=f"/samples/{sample_nr}?saved=true", status_code=303)
        response.set_cookie(
            key=LAST_SAMPLE_COOKIE,
            value=str(sample_nr),
            path="/",
            samesite="lax",
        )
        return response

    response = templates.TemplateResponse(
        "sample_detail.html",
        build_sample_detail_context(
            request,
            overview=overview,
            service=service,
            saved=False,
            save_error=save_error,
            sample_field_errors=field_errors,
            sample_form_values=submitted_fields,
            sample_edit_initial_mode="editing",
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

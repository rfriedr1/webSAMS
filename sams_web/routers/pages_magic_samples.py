"""Magic Nav and sample/preparation/target detail routes."""

from __future__ import annotations

import re
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.routers.pages_shared import (
    LAST_SAMPLE_COOKIE,
    append_magic_feedback,
    resolve_jump_redirect_url,
    resolve_magic_identifier,
    templates,
)
from sams_web.services import SamsService
from sams_web.viewmodels import detail_sections as ds

router = APIRouter()

SAMPLE_EDIT_FORM_ID = "sample-detail-edit-form"
SAMPLE_READ_ONLY_FIELDS = ("sample_nr", "project_nr")
SAMPLE_REQUIRED_FIELDS = (
    "sample__type",
    "sample__material",
    "sample__fraction",
    "sample__project_in_date",
    "sample__project_desired_date",
)
PREPARATION_EDIT_FORM_ID = "preparation-detail-edit-form"
PREPARATION_READ_ONLY_FIELDS = ("sample_nr", "prep_nr")
PREPARATION_REQUIRED_FIELDS: tuple[str, ...] = ()
TARGET_EDIT_FORM_ID = "target-detail-edit-form"
TARGET_READ_ONLY_FIELDS = ("sample_nr", "prep_nr", "target_nr", "target_id")
TARGET_REQUIRED_FIELDS: tuple[str, ...] = ()


def _build_sample_detail_context(
    request: Request,
    *,
    sample_nr: int,
    overview: dict[str, object],
    service: SamsService,
    saved: bool = False,
    save_error: str | None = None,
    sample_field_errors: dict[str, str] | None = None,
    sample_form_values: dict[str, str] | None = None,
    sample_edit_initial_mode: str = "view",
    creation_notice: str | None = None,
) -> dict[str, object]:
    sample = overview["sample"]
    project = overview["project"]
    preparations = overview["preparations"]
    default_target_prep_nr = preparations[0].prep_nr if preparations else None

    return {
        "request": request,
        "sample": sample,
        "project": project,
        "user": overview["user"],
        "preparations": preparations,
        "targets_by_prep": overview["targets_by_prep"],
        "sample_targets_total": overview["sample_targets_total"],
        "targets": overview["targets"],
        "previous_sample_nr": overview["previous_sample_nr"],
        "next_sample_nr": overview["next_sample_nr"],
        "sample_count": overview["sample_count"],
        "max_sample_nr": overview["max_sample_nr"],
        "sample_sections": ds.build_sample_sections(sample, project=project),
        "sample_c14_age_display": ds.format_sample_value("c14_age", sample.c14_age),
        "sample_user_comment_display": ds.format_sample_value("user_comment", sample.user_comment),
        "sample_lab_comment_display": ds.format_sample_value("lab_comment", sample.lab_comment),
        "sample_edit_form_id": SAMPLE_EDIT_FORM_ID,
        "sample_read_only_fields": SAMPLE_READ_ONLY_FIELDS,
        "sample_required_fields": SAMPLE_REQUIRED_FIELDS,
        "sample_select_options": service.get_sample_edit_select_options(),
        "sample_field_errors": sample_field_errors or {},
        "sample_form_values": sample_form_values or {},
        "sample_save_error": save_error,
        "sample_saved": saved,
        "sample_edit_initial_mode": sample_edit_initial_mode,
        "sample_creation_notice": creation_notice,
        "sample_default_target_prep_nr": default_target_prep_nr,
    }


def _build_preparation_detail_context(
    request: Request,
    *,
    sample_nr: int,
    prep_nr: int,
    data: dict[str, object],
    service: SamsService,
    saved: bool = False,
    save_error: str | None = None,
    preparation_field_errors: dict[str, str] | None = None,
    preparation_form_values: dict[str, str] | None = None,
    preparation_edit_initial_mode: str = "view",
) -> dict[str, object]:
    return {
        "request": request,
        "sample": data["sample"],
        "project": data["project"],
        "user": data["user"],
        "preparation": data["preparation"],
        "preparation_sections": ds.build_preparation_sections(data["preparation"]),
        "targets": data["targets"],
        "targets_total": data["targets_total"],
        "previous_prep_nr": data["previous_prep_nr"],
        "next_prep_nr": data["next_prep_nr"],
        "preparation_count": data["preparation_count"],
        "max_prep_nr": data["max_prep_nr"],
        "preparation_edit_form_id": PREPARATION_EDIT_FORM_ID,
        "preparation_read_only_fields": PREPARATION_READ_ONLY_FIELDS,
        "preparation_required_fields": PREPARATION_REQUIRED_FIELDS,
        "preparation_select_options": service.get_preparation_edit_select_options(),
        "preparation_field_errors": preparation_field_errors or {},
        "preparation_form_values": preparation_form_values or {},
        "preparation_save_error": save_error,
        "preparation_saved": saved,
        "preparation_edit_initial_mode": preparation_edit_initial_mode,
    }


def _build_target_detail_context(
    request: Request,
    *,
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    data: dict[str, object],
    saved: bool = False,
    save_error: str | None = None,
    target_field_errors: dict[str, str] | None = None,
    target_form_values: dict[str, str] | None = None,
    target_edit_initial_mode: str = "view",
) -> dict[str, object]:
    target = data["target"]
    target_sections = ds.build_target_sections(target)
    for section in target_sections:
        for row in section.get("rows", []):
            if row.get("key") != "magazine":
                continue
            raw_magazine = row.get("raw_value")
            if raw_magazine is None:
                continue
            magazine_value = str(raw_magazine).strip()
            if magazine_value == "":
                continue
            row["action_url"] = f"/lab/analysis?magazine={quote_plus(magazine_value)}#tbl-magazine-targets"
            row["action_title"] = f"Show all targets in magazine {magazine_value}"

    return {
        "request": request,
        "sample": data["sample"],
        "project": data["project"],
        "user": data["user"],
        "preparation": data["preparation"],
        "target": target,
        "target_prep_options": data.get("preparations", []),
        "target_sections": target_sections,
        "previous_target_nr": data["previous_target_nr"],
        "next_target_nr": data["next_target_nr"],
        "target_count": data["target_count"],
        "max_target_nr": data["max_target_nr"],
        "target_fm_display": ds.format_target_indicator("fm", target.fm),
        "target_fm_sig_display": ds.format_target_indicator("fm_sig", target.fm_sig),
        "target_dc13_display": ds.format_target_indicator("dc13", target.dc13),
        "target_c14_age_display": ds.format_target_indicator("c14_age", target.c14_age),
        "target_c14_age_sig_display": ds.format_target_indicator("c14_age_sig", target.c14_age_sig),
        "target_edit_form_id": TARGET_EDIT_FORM_ID,
        "target_read_only_fields": TARGET_READ_ONLY_FIELDS,
        "target_required_fields": TARGET_REQUIRED_FIELDS,
        "target_select_options": {},
        "target_field_errors": target_field_errors or {},
        "target_form_values": target_form_values or {},
        "target_save_error": save_error,
        "target_saved": saved,
        "target_edit_initial_mode": target_edit_initial_mode,
        "sample_nr": sample_nr,
        "prep_nr": prep_nr,
        "target_nr": target_nr,
    }


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
        _build_sample_detail_context(
            request,
            sample_nr=sample_nr,
            overview=overview,
            service=service,
            saved=saved,
            creation_notice=_build_sample_creation_notice(
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


def _build_sample_creation_notice(
    *,
    created: str | None,
    created_prep: int | None,
    created_target: int | None,
) -> str | None:
    if created == "prep" and created_prep is not None:
        return f"Created preparation #{created_prep} and seeded target #1."
    if created == "target" and created_prep is not None and created_target is not None:
        return f"Created target #{created_target} in preparation #{created_prep}."
    return None


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
        if isinstance(value, str):
            submitted_fields[key] = value
        else:
            submitted_fields[key] = str(value)

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
        _build_sample_detail_context(
            request,
            sample_nr=sample_nr,
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
        _build_preparation_detail_context(
            request,
            sample_nr=sample_nr,
            prep_nr=prep_nr,
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
        _build_preparation_detail_context(
            request,
            sample_nr=sample_nr,
            prep_nr=prep_nr,
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

    def _target_url(resolved_target_nr: int) -> str:
        return f"/samples/{sample_nr}/preparations/{prep_nr}/targets/{resolved_target_nr}"

    if jump_target is not None:
        fallback_url = _target_url(target_nr)
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_target,
            current_id=target_nr,
            max_id=int(data.get("max_target_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=_target_url,
            exists_fn=lambda jump_id: service.target_exists(sample_nr, prep_nr, jump_id),
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    response = templates.TemplateResponse(
        "target_detail.html",
        _build_target_detail_context(
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
        _build_target_detail_context(
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

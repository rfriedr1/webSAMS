"""User and project page routes."""

from __future__ import annotations

import traceback

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.config import get_settings
from sams_web.dependencies import get_service
from sams_web.routers.pages_shared import logger, resolve_jump_redirect_url, templates
from sams_web.services import SamsService
from sams_web.viewmodels import detail_sections as ds

router = APIRouter()

PROJECT_EDIT_FORM_ID = "project-detail-edit-form"
PROJECT_READ_ONLY_FIELDS = ("project_nr", "user_nr")
PROJECT_REQUIRED_FIELDS: tuple[str, ...] = ()
USER_EDIT_FORM_ID = "user-detail-edit-form"
USER_READ_ONLY_FIELDS = ("user_nr",)
USER_REQUIRED_FIELDS: tuple[str, ...] = ()


def _build_project_detail_context(
    request: Request,
    *,
    data: dict[str, object],
    service: SamsService,
    saved: bool = False,
    save_error: str | None = None,
    project_field_errors: dict[str, str] | None = None,
    project_form_values: dict[str, str] | None = None,
    project_edit_initial_mode: str = "view",
) -> dict[str, object]:
    project = data["project"]
    samples = data["samples"]
    return {
        "request": request,
        "project": project,
        "user": data["user"],
        "samples": samples,
        "sample_count": len(samples),
        "project_sections": ds.build_project_sections(project),
        "previous_project_nr": data["previous_project_nr"],
        "next_project_nr": data["next_project_nr"],
        "project_count": data["project_count"],
        "max_project_nr": data["max_project_nr"],
        "project_edit_form_id": PROJECT_EDIT_FORM_ID,
        "project_read_only_fields": PROJECT_READ_ONLY_FIELDS,
        "project_required_fields": PROJECT_REQUIRED_FIELDS,
        "project_select_options": service.get_project_edit_select_options(),
        "project_field_errors": project_field_errors or {},
        "project_form_values": project_form_values or {},
        "project_save_error": save_error,
        "project_saved": saved,
        "project_edit_initial_mode": project_edit_initial_mode,
    }


def _build_user_detail_context(
    request: Request,
    *,
    data: dict[str, object],
    saved: bool = False,
    save_error: str | None = None,
    user_field_errors: dict[str, str] | None = None,
    user_form_values: dict[str, str] | None = None,
    user_edit_initial_mode: str = "view",
) -> dict[str, object]:
    return {
        "request": request,
        "user": data["user"],
        "user_sections": ds.build_user_sections(data["user"]),
        "projects": data["projects"],
        "previous_user_nr": data["previous_user_nr"],
        "next_user_nr": data["next_user_nr"],
        "user_count": data["user_count"],
        "max_user_nr": data["max_user_nr"],
        "user_edit_form_id": USER_EDIT_FORM_ID,
        "user_read_only_fields": USER_READ_ONLY_FIELDS,
        "user_required_fields": USER_REQUIRED_FIELDS,
        "user_select_options": {},
        "user_field_errors": user_field_errors or {},
        "user_form_values": user_form_values or {},
        "user_save_error": save_error,
        "user_saved": saved,
        "user_edit_initial_mode": user_edit_initial_mode,
    }


@router.get("/users")
def users_page(
    request: Request,
    service: SamsService = Depends(get_service),
):
    settings = get_settings()
    users = []
    error: str | None = None
    error_trace: str | None = None
    try:
        users = service.list_users()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed loading users list")
        if settings.debug:
            error = f"{type(exc).__name__}: {exc}"
            error_trace = traceback.format_exc()
        else:
            error = "Failed to load users. Enable SAMS_DEBUG=true for traceback details."

    return templates.TemplateResponse(
        "users.html",
        {
            "request": request,
            "users": users,
            "error": error,
            "error_trace": error_trace,
        },
    )


@router.post("/users/new")
def create_user_form(
    last_name: str = Form(...),
    first_name: str | None = Form(default=None),
    organisation: str | None = Form(default=None),
    institute: str | None = Form(default=None),
    email: str | None = Form(default=None),
    service: SamsService = Depends(get_service),
):
    user = service.create_user(
        {
            "last_name": last_name,
            "first_name": first_name,
            "organisation": organisation,
            "institute": institute,
            "email": email,
        }
    )
    return RedirectResponse(url=f"/users/{user.user_nr}", status_code=303)


@router.get("/users/{user_nr}")
def user_detail_page(
    request: Request,
    user_nr: int,
    jump_user: str | None = Query(default=None),
    saved: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_user_details(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")

    if jump_user is not None:
        fallback_url = f"/users/{user_nr}"
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_user,
            current_id=user_nr,
            max_id=int(data.get("max_user_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=lambda jump_id: f"/users/{jump_id}",
            exists_fn=service.user_exists,
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    return templates.TemplateResponse(
        "user_detail.html",
        _build_user_detail_context(
            request,
            data=data,
            saved=saved,
        ),
    )


@router.post("/users/{user_nr}/save")
async def save_user_detail_page(
    request: Request,
    user_nr: int,
    service: SamsService = Depends(get_service),
):
    data = service.get_user_details(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")

    raw_form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key, value in raw_form.items():
        if not key.startswith("user__"):
            continue
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    saved, field_errors, save_error = service.update_user_detail(user_nr, submitted_fields)
    if saved:
        return RedirectResponse(url=f"/users/{user_nr}?saved=true", status_code=303)

    return templates.TemplateResponse(
        "user_detail.html",
        _build_user_detail_context(
            request,
            data=data,
            saved=False,
            save_error=save_error,
            user_field_errors=field_errors,
            user_form_values=submitted_fields,
            user_edit_initial_mode="editing",
        ),
        status_code=422,
    )


@router.get("/users/{user_nr}/projects")
def user_projects_page(request: Request, user_nr: int, service: SamsService = Depends(get_service)):
    data = service.get_user_details(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return RedirectResponse(url=f"/users/{user_nr}", status_code=307)


@router.get("/projects")
def projects_page(
    request: Request,
    days_window: int = Query(default=300, ge=1, le=3650),
    service: SamsService = Depends(get_service),
):
    settings = get_settings()
    projects_in_progress: list[dict[str, object]] = []
    projects_in_progress_error: str | None = None
    projects_in_progress_error_trace: str | None = None
    projects = []
    error: str | None = None
    error_trace: str | None = None
    try:
        projects_in_progress = service.get_projects_in_progress(days_window=days_window)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed loading projects-in-progress list")
        if settings.debug:
            projects_in_progress_error = f"{type(exc).__name__}: {exc}"
            projects_in_progress_error_trace = traceback.format_exc()
        else:
            projects_in_progress_error = "Failed to load projects in progress. Enable SAMS_DEBUG=true for traceback details."
    try:
        projects = service.list_projects()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed loading projects list")
        if settings.debug:
            error = f"{type(exc).__name__}: {exc}"
            error_trace = traceback.format_exc()
        else:
            error = "Failed to load projects. Enable SAMS_DEBUG=true for traceback details."

    return templates.TemplateResponse(
        "projects.html",
        {
            "request": request,
            "days_window": days_window,
            "projects_in_progress": projects_in_progress,
            "projects_in_progress_error": projects_in_progress_error,
            "projects_in_progress_error_trace": projects_in_progress_error_trace,
            "projects": projects,
            "error": error,
            "error_trace": error_trace,
        },
    )


@router.get("/projects/{project_nr}")
def project_detail_page(
    request: Request,
    project_nr: int,
    jump_project: str | None = Query(default=None),
    saved: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_project_details(project_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")

    if jump_project is not None:
        fallback_url = f"/projects/{project_nr}"
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_project,
            current_id=project_nr,
            max_id=int(data.get("max_project_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=lambda jump_id: f"/projects/{jump_id}",
            exists_fn=service.project_exists,
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    return templates.TemplateResponse(
        "project_detail.html",
        _build_project_detail_context(
            request,
            data=data,
            service=service,
            saved=saved,
        ),
    )


@router.post("/projects/{project_nr}/save")
async def save_project_detail_page(
    request: Request,
    project_nr: int,
    service: SamsService = Depends(get_service),
):
    data = service.get_project_details(project_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")

    raw_form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key, value in raw_form.items():
        if not key.startswith("project__"):
            continue
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    saved, field_errors, save_error = service.update_project_detail(project_nr, submitted_fields)
    if saved:
        return RedirectResponse(url=f"/projects/{project_nr}?saved=true", status_code=303)

    return templates.TemplateResponse(
        "project_detail.html",
        _build_project_detail_context(
            request,
            data=data,
            service=service,
            saved=False,
            save_error=save_error,
            project_field_errors=field_errors,
            project_form_values=submitted_fields,
            project_edit_initial_mode="editing",
        ),
        status_code=422,
    )


@router.post("/projects/new")
def create_project_form(
    user_nr: int = Form(...),
    project: str = Form(...),
    service: SamsService = Depends(get_service),
):
    created = service.add_new_project_by_user_nr(user_nr=user_nr, project_name=project)
    return RedirectResponse(url=f"/projects/{created.project_nr}", status_code=303)


@router.get("/projects/{project_nr}/samples")
def project_samples_page(request: Request, project_nr: int, service: SamsService = Depends(get_service)):
    data = service.get_project_details(project_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return RedirectResponse(url=f"/projects/{project_nr}", status_code=307)

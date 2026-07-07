"""Submitter and project page routes."""

from __future__ import annotations

import traceback

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.config import get_settings
from sams_web.dependencies import get_service
from sams_web.detail_page import EditFormState, NavCursor, build_detail_page_context
from sams_web.routers.pages_shared import logger, resolve_jump_redirect_url, templates
from sams_web.services import SamsService
from sams_web.viewmodels.detail_sections_user_project import (
    PROJECT_DETAIL_PAGE,
    SUBMITTER_DETAIL_PAGE,
)

router = APIRouter()


def _project_extra_keys(data: dict[str, object]) -> dict[str, object]:
    samples = data["samples"]
    return {
        "user": data["user"],
        "samples": samples,
        "sample_count": len(samples),
    }


def _project_cursor(data: dict[str, object]) -> NavCursor:
    return NavCursor(
        previous_nr=data["previous_project_nr"],
        next_nr=data["next_project_nr"],
        count=data["project_count"],
        max_nr=data["max_project_nr"],
    )


def _submitter_extra_keys(data: dict[str, object]) -> dict[str, object]:
    return {
        "projects": data["projects"],
    }


def _submitter_cursor(data: dict[str, object]) -> NavCursor:
    return NavCursor(
        previous_nr=data["previous_user_nr"],
        next_nr=data["next_user_nr"],
        count=data["user_count"],
        max_nr=data["max_user_nr"],
    )


SUBMITTER_LIST_DEFAULT_LIMIT = 500
PROJECT_LIST_DEFAULT_LIMIT = 500


@router.get("/submitters")
def submitters_page(
    request: Request,
    show_all: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    """Submitters list. Capped at SUBMITTER_LIST_DEFAULT_LIMIT rows by
    default — the full set is ~2 700 rows and rendering all of them
    pushed the page to ~860 KB. Users who really want everything can
    pass `?show_all=true`."""
    settings = get_settings()
    submitters = []
    error: str | None = None
    error_trace: str | None = None
    effective_limit = None if show_all else SUBMITTER_LIST_DEFAULT_LIMIT
    try:
        submitters = service.list_submitters(limit=effective_limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed loading submitters list")
        if settings.debug:
            error = f"{type(exc).__name__}: {exc}"
            error_trace = traceback.format_exc()
        else:
            error = "Failed to load submitters. Enable SAMS_DEBUG=true for traceback details."

    is_truncated = (
        not show_all
        and len(submitters) >= SUBMITTER_LIST_DEFAULT_LIMIT
    )

    return templates.TemplateResponse(
        "submitters.html",
        {
            "request": request,
            "submitters": submitters,
            "error": error,
            "error_trace": error_trace,
            "is_truncated": is_truncated,
            "truncated_limit": SUBMITTER_LIST_DEFAULT_LIMIT,
            "show_all": show_all,
        },
    )


@router.post("/submitters/new")
def create_submitter_form(
    last_name: str = Form(...),
    first_name: str | None = Form(default=None),
    organisation: str | None = Form(default=None),
    institute: str | None = Form(default=None),
    email: str | None = Form(default=None),
    service: SamsService = Depends(get_service),
):
    submitter = service.create_submitter(
        {
            "last_name": last_name,
            "first_name": first_name,
            "organisation": organisation,
            "institute": institute,
            "email": email,
        }
    )
    return RedirectResponse(url=f"/submitters/{submitter.user_nr}", status_code=303)


@router.get("/submitters/{user_nr}")
def submitter_detail_page(
    request: Request,
    user_nr: int,
    jump_submitter: str | None = Query(default=None),
    saved: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_submitter_details(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Submitter not found")

    if jump_submitter is not None:
        fallback_url = f"/submitters/{user_nr}"
        redirect_url = resolve_jump_redirect_url(
            jump_value=jump_submitter,
            current_id=user_nr,
            max_id=int(data.get("max_user_nr") or 0),
            fallback_url=fallback_url,
            target_url_for=lambda jump_id: f"/submitters/{jump_id}",
            exists_fn=service.submitter_exists,
        )
        if redirect_url is not None:
            return RedirectResponse(url=redirect_url, status_code=303)

    return templates.TemplateResponse(
        "submitter_detail.html",
        build_detail_page_context(
            request,
            SUBMITTER_DETAIL_PAGE,
            entity=data["user"],
            cursor=_submitter_cursor(data),
            edit_state=EditFormState(saved=saved),
            service=service,
            extra=_submitter_extra_keys(data),
        ),
    )


@router.post("/submitters/{user_nr}/save")
async def save_submitter_detail_page(
    request: Request,
    user_nr: int,
    service: SamsService = Depends(get_service),
):
    data = service.get_submitter_details(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Submitter not found")

    raw_form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key, value in raw_form.items():
        if not key.startswith("user__"):
            continue
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    saved, field_errors, save_error = service.update_submitter_detail(user_nr, submitted_fields)
    if saved:
        return RedirectResponse(url=f"/submitters/{user_nr}?saved=true", status_code=303)

    return templates.TemplateResponse(
        "submitter_detail.html",
        build_detail_page_context(
            request,
            SUBMITTER_DETAIL_PAGE,
            entity=data["user"],
            cursor=_submitter_cursor(data),
            edit_state=EditFormState(
                saved=False,
                save_error=save_error,
                field_errors=field_errors,
                form_values=submitted_fields,
                edit_initial_mode="editing",
            ),
            service=service,
            extra=_submitter_extra_keys(data),
        ),
        status_code=422,
    )


@router.get("/submitters/{user_nr}/projects")
def submitter_projects_page(request: Request, user_nr: int, service: SamsService = Depends(get_service)):
    data = service.get_submitter_details(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Submitter not found")
    return RedirectResponse(url=f"/submitters/{user_nr}", status_code=307)


@router.get("/projects")
def projects_page(
    request: Request,
    days_window: int = Query(default=300, ge=1, le=3650),
    show_all: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    """Projects list. The "All Projects" table is capped at
    PROJECT_LIST_DEFAULT_LIMIT rows by default — the full set runs
    ~13 000 rows and rendered to a ~9.4 MB HTML response. The "Projects
    in Progress" table is already filtered by `days_window` so it stays
    naturally small."""
    settings = get_settings()
    projects_in_progress: list[dict[str, object]] = []
    projects_in_progress_error: str | None = None
    projects_in_progress_error_trace: str | None = None
    projects = []
    error: str | None = None
    error_trace: str | None = None
    effective_limit = None if show_all else PROJECT_LIST_DEFAULT_LIMIT
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
        projects = service.list_projects(limit=effective_limit)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed loading projects list")
        if settings.debug:
            error = f"{type(exc).__name__}: {exc}"
            error_trace = traceback.format_exc()
        else:
            error = "Failed to load projects. Enable SAMS_DEBUG=true for traceback details."

    is_truncated = (
        not show_all
        and len(projects) >= PROJECT_LIST_DEFAULT_LIMIT
    )

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
            "is_truncated": is_truncated,
            "truncated_limit": PROJECT_LIST_DEFAULT_LIMIT,
            "show_all": show_all,
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
        build_detail_page_context(
            request,
            PROJECT_DETAIL_PAGE,
            entity=data["project"],
            cursor=_project_cursor(data),
            edit_state=EditFormState(saved=saved),
            service=service,
            extra=_project_extra_keys(data),
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
        build_detail_page_context(
            request,
            PROJECT_DETAIL_PAGE,
            entity=data["project"],
            cursor=_project_cursor(data),
            edit_state=EditFormState(
                saved=False,
                save_error=save_error,
                field_errors=field_errors,
                form_values=submitted_fields,
                edit_initial_mode="editing",
            ),
            service=service,
            extra=_project_extra_keys(data),
        ),
        status_code=422,
    )


@router.post("/projects/new")
def create_project_form(
    user_nr: int = Form(...),
    project: str = Form(...),
    service: SamsService = Depends(get_service),
):
    created = service.add_new_project_by_submitter_nr(user_nr=user_nr, project_name=project)
    return RedirectResponse(url=f"/projects/{created.project_nr}", status_code=303)


@router.get("/projects/{project_nr}/samples")
def project_samples_page(request: Request, project_nr: int, service: SamsService = Depends(get_service)):
    data = service.get_project_details(project_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return RedirectResponse(url=f"/projects/{project_nr}", status_code=307)

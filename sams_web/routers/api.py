"""JSON API endpoints for SAMS."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.inspection import inspect

from sams_web.dependencies import get_service
from sams_web.schemas import (
    DashboardCounts,
    ProjectCreate,
    ProjectRead,
    SampleCreate,
    SampleRead,
    UserCreate,
    UserRead,
)
from sams_web.services import SamsService

router = APIRouter(prefix="/api", tags=["api"])


def _model_to_dict(model: Any) -> dict[str, Any]:
    return {column.key: getattr(model, column.key) for column in inspect(model).mapper.column_attrs}


def _serialize_details(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample": _model_to_dict(payload["sample"]),
        "project": _model_to_dict(payload["project"]) if payload.get("project") else None,
        "user": _model_to_dict(payload["user"]) if payload.get("user") else None,
        "preparations": [_model_to_dict(row) for row in payload.get("preparations", [])],
        "targets": [_model_to_dict(row) for row in payload.get("targets", [])],
    }


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/dashboard/counts", response_model=DashboardCounts)
def dashboard_counts(
    show_on_hold: bool = False,
    service: SamsService = Depends(get_service),
) -> DashboardCounts:
    return DashboardCounts(**service.get_dashboard(show_on_hold=show_on_hold)["counts"])


@router.get("/dashboard/tables")
def dashboard_tables(
    show_on_hold: bool = False,
    service: SamsService = Depends(get_service),
) -> dict[str, list[dict[str, Any]]]:
    return service.get_dashboard(show_on_hold=show_on_hold)["tables"]


@router.get("/users", response_model=list[UserRead])
def list_users(
    query: str | None = Query(default=None, alias="q"),
    service: SamsService = Depends(get_service),
) -> list[UserRead]:
    return [UserRead.model_validate(user) for user in service.list_users(query=query)]


@router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(payload: UserCreate, service: SamsService = Depends(get_service)) -> UserRead:
    user = service.create_user(payload.model_dump())
    return UserRead.model_validate(user)


@router.get("/users/{user_nr}/projects", response_model=list[ProjectRead])
def list_user_projects(user_nr: int, service: SamsService = Depends(get_service)) -> list[ProjectRead]:
    data = service.get_user_projects(user_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="User not found")
    return [ProjectRead.model_validate(project) for project in data["projects"]]


@router.post("/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, service: SamsService = Depends(get_service)) -> ProjectRead:
    project = service.create_project(payload.model_dump())
    return ProjectRead.model_validate(project)


@router.get("/projects/{project_nr}/samples", response_model=list[SampleRead])
def list_project_samples(project_nr: int, service: SamsService = Depends(get_service)) -> list[SampleRead]:
    data = service.get_project_samples(project_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return [SampleRead.model_validate(sample) for sample in data["samples"]]


@router.post("/samples", response_model=SampleRead, status_code=status.HTTP_201_CREATED)
def create_sample(payload: SampleCreate, service: SamsService = Depends(get_service)) -> SampleRead:
    sample = service.create_sample(payload.model_dump(exclude_none=True), with_blank_records=True)
    return SampleRead.model_validate(sample)


@router.get("/samples/{sample_nr}")
def sample_details(sample_nr: int, service: SamsService = Depends(get_service)) -> dict[str, Any]:
    data = service.get_sample_details(sample_nr)
    if data is None:
        raise HTTPException(status_code=404, detail="Sample not found")
    return _serialize_details(data)


@router.post("/samples/{sample_nr}/set-running")
def set_project_running(sample_nr: int, service: SamsService = Depends(get_service)) -> dict[str, Any]:
    changed = service.set_project_running(sample_nr)
    return {"updated": changed}


@router.post("/samples/{sample_nr}/transfer-age")
def transfer_age(
    sample_nr: int,
    prep_nr: int = 1,
    target_nr: int = 1,
    service: SamsService = Depends(get_service),
) -> dict[str, Any]:
    changed = service.transfer_age_from_target(sample_nr, prep_nr=prep_nr, target_nr=target_nr)
    return {"updated": changed}


@router.post("/maintenance/check-project-status")
def check_project_status(service: SamsService = Depends(get_service)) -> dict[str, int]:
    closed = service.check_project_status()
    return {"closed_projects": closed}


@router.get("/lookups")
def get_lookups(service: SamsService = Depends(get_service)) -> dict[str, list[str]]:
    return service.get_lookups()


@router.get("/setup/sections")
def setup_sections(service: SamsService = Depends(get_service)) -> list[dict[str, Any]]:
    return service.list_setup_sections()


@router.get("/setup/{section_key}")
def get_setup_section(section_key: str, service: SamsService = Depends(get_service)) -> dict[str, Any]:
    try:
        return service.get_setup_section(section_key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/setup/{section_key}")
def update_setup_section(
    section_key: str,
    payload: dict[str, dict[str, Any]],
    service: SamsService = Depends(get_service),
) -> dict[str, Any]:
    try:
        return service.update_setup_section(section_key, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/search")
def search(
    context: str,
    phrase: str,
    limit: int = 200,
    service: SamsService = Depends(get_service),
) -> list[dict[str, Any]]:
    try:
        return service.search(context=context, phrase=phrase, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reports/projects-in-progress")
def projects_in_progress_report(
    days_window: int = Query(default=300, ge=1, le=3650),
    include_internal: bool = Query(default=False),
    service: SamsService = Depends(get_service),
) -> list[dict[str, Any]]:
    return service.get_projects_in_progress(
        days_window=days_window,
        include_internal=include_internal,
    )

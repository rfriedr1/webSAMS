"""Record-action routes: preview (JSON) and run, for project and submitter
pages. The actions themselves live in `sams_web/record_actions.py`."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import JSONResponse, RedirectResponse

from sams_web import record_actions
from sams_web.access import Permission, guarded
from sams_web.dependencies import get_service
from sams_web.routers.pages_shared import logger
from sams_web.services import SamsService

router = APIRouter()

_OWNER_PATHS = {"project": "projects", "submitter": "submitters"}


def _resolve(service: SamsService, owner: str, owner_nr: int, key: str) -> record_actions.RecordAction:
    if not record_actions.owner_exists(service, owner, owner_nr):
        raise HTTPException(status_code=404, detail=f"{owner.capitalize()} not found")
    try:
        return record_actions.action_for(owner, key)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown action") from None


def _preview(service: SamsService, owner: str, owner_nr: int, key: str, nrs: str | None) -> JSONResponse:
    action = _resolve(service, owner, owner_nr, key)
    try:
        selected = record_actions.parse_selection(nrs)
        result = record_actions.plan(service, action, owner, owner_nr, selected)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=422)
    return JSONResponse(result.as_json())


def _run(service: SamsService, owner: str, owner_nr: int, key: str, nrs: str) -> RedirectResponse:
    action = _resolve(service, owner, owner_nr, key)
    back = f"/{_OWNER_PATHS[owner]}/{owner_nr}"
    try:
        selected = record_actions.parse_selection(nrs)
        outcome = record_actions.apply(service, action, owner, owner_nr, selected)
    except ValueError as exc:
        return RedirectResponse(url=f"{back}?{urlencode({'action_error': str(exc)})}", status_code=303)
    logger.info(
        "Record action %s on %s %s: %s changed, %s unchanged, %s refused",
        action.key, owner, owner_nr, outcome.changed, outcome.unchanged, len(outcome.refused),
    )
    param = "action_error" if outcome.changed == 0 and outcome.refused else "action_notice"
    return RedirectResponse(url=f"{back}?{urlencode({param: outcome.notice()})}", status_code=303)


@router.get(
    "/projects/{project_nr}/actions/{key}/preview",
    dependencies=guarded(Permission.EDIT_RECORDS),
)
def project_action_preview(
    project_nr: int,
    key: str,
    nrs: str | None = Query(default=None),
    service: SamsService = Depends(get_service),
):
    return _preview(service, "project", project_nr, key, nrs)


@router.post(
    "/projects/{project_nr}/actions/{key}",
    dependencies=guarded(Permission.EDIT_RECORDS),
)
def project_action_run(
    project_nr: int,
    key: str,
    nrs: str = Form(default=""),
    service: SamsService = Depends(get_service),
):
    return _run(service, "project", project_nr, key, nrs)


@router.get(
    "/submitters/{user_nr}/actions/{key}/preview",
    dependencies=guarded(Permission.EDIT_RECORDS),
)
def submitter_action_preview(
    user_nr: int,
    key: str,
    nrs: str | None = Query(default=None),
    service: SamsService = Depends(get_service),
):
    return _preview(service, "submitter", user_nr, key, nrs)


@router.post(
    "/submitters/{user_nr}/actions/{key}",
    dependencies=guarded(Permission.EDIT_RECORDS),
)
def submitter_action_run(
    user_nr: int,
    key: str,
    nrs: str = Form(default=""),
    service: SamsService = Depends(get_service),
):
    return _run(service, "submitter", user_nr, key, nrs)

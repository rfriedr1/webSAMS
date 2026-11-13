"""Sample-import wizard routes.

Three endpoints:

- `GET  /samples/import`         — the wizard shell (server-rendered chrome)
- `POST /samples/import/parse`   — multipart upload → JSON review payload
- `POST /samples/import/commit`  — approved JSON payload → created records

The wizard body is driven client-side from the parse payload. That keeps
the reviewed draft in browser memory between steps, so re-mapping a
column or fixing a material updates the preview instantly without a
round-trip, and no server-side session state has to be invented.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from sams_web.access import Permission, guarded
from fastapi.responses import FileResponse, JSONResponse

from sams_web.dependencies import get_service
from sams_web.import_settings import EmailSettingsStore
from sams_web.routers.pages_shared import templates
from sams_web.sample_import.commit import ImportCommitError
from sams_web.sample_import.diagnostics import describe_failure, format_for_log
from sams_web.sample_import.mailer import EmailError, build_confirmation, send_email
from sams_web.sample_import.service import (
    commit_submission,
    parse_submission,
    projects_for_submitter,
    search_submitters,
    suggest_project_variant,
)
from sams_web.sample_import.workbook import MAX_UPLOAD_BYTES, WorkbookError
from sams_web.services import SamsService

router = APIRouter()
logger = logging.getLogger(__name__)

#: Blank submission template shipped with the app, offered for download
#: on step 1 so operators can hand customers the current version.
TEMPLATE_PATH = (
    Path(__file__).resolve().parent.parent.parent / "templates" / "Submit_Samples_Template.xlsx"
)


@router.get("/samples/import")
def sample_import_page(request: Request):
    return templates.TemplateResponse(request, "sample_import.html",
        {
            "request": request,
            "title": "Import Samples",
            "max_upload_mb": MAX_UPLOAD_BYTES // 1_048_576,
            "template_available": TEMPLATE_PATH.exists(),
        },
    )


@router.get("/samples/import/template")
def sample_import_template():
    """Download the blank submission template."""
    if not TEMPLATE_PATH.exists():
        return JSONResponse({"detail": "Template file is not available."}, status_code=404)
    return FileResponse(
        TEMPLATE_PATH,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename="Submit_Samples_Template.xlsx",
    )


@router.post("/samples/import/parse", dependencies=guarded(Permission.EDIT_RECORDS))
async def sample_import_parse(
    file: UploadFile = File(...),
    service: SamsService = Depends(get_service),
):
    """Parse an uploaded workbook into a review payload."""
    data = await file.read()
    try:
        _draft, payload = parse_submission(
            service, data, filename=file.filename or "upload.xlsx"
        )
    except WorkbookError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001 - never leak a stack trace to the browser
        technical = describe_failure(
            exc,
            stage="Reading the workbook",
            context={"file": file.filename, "size_bytes": len(data)},
        )
        logger.exception("Failed parsing submission workbook: %s", format_for_log(technical))
        return JSONResponse(
            {
                "detail": (
                    "The workbook could not be parsed. Check that it is a filled-in "
                    "submission sheet, or contact support if it looks correct."
                ),
                "technical": technical,
            },
            status_code=500,
        )
    return JSONResponse(payload)


@router.post("/samples/import/commit", dependencies=guarded(Permission.EDIT_RECORDS))
async def sample_import_commit(
    request: Request,
    service: SamsService = Depends(get_service),
):
    """Create submitter / project / samples from the approved payload."""
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "Malformed request payload."}, status_code=400)

    try:
        result = commit_submission(service, payload)
    except ImportCommitError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:  # noqa: BLE001
        service.session.rollback()
        technical = describe_failure(
            exc,
            stage="Saving the import (one transaction, rolled back)",
            context={
                "project": (payload.get("project") or {}).get("project"),
                "submitter_nr": (payload.get("submitter") or {}).get("user_nr"),
                "samples_in_payload": len(payload.get("samples") or []),
            },
        )
        logger.exception("Failed committing sample import: %s", format_for_log(technical))
        return JSONResponse(
            {
                "detail": (
                    "The import could not be saved and nothing was written. "
                    "Please try again, or contact support if this persists."
                ),
                "technical": technical,
            },
            status_code=500,
        )
    return JSONResponse(result.as_dict())


@router.get("/samples/import/submitters")
def sample_import_submitters(
    q: str = Query(default="", max_length=120),
    service: SamsService = Depends(get_service),
):
    """Backing search for the 'browse all submitters' picker in step 2."""
    return JSONResponse({"submitters": search_submitters(service, q)})


@router.get("/samples/import/projects")
def sample_import_projects(
    user_nr: int = Query(...),
    name: str = Query(default=""),
    service: SamsService = Depends(get_service),
):
    """Existing projects for a submitter, for the duplicate-project check.

    Called whenever the operator changes the selected submitter, so the
    'this customer already has a project called X' prompt stays correct.
    """
    projects = projects_for_submitter(service, user_nr)
    return JSONResponse(
        {
            "projects": projects,
            "variant_suggestion": suggest_project_variant(name),
        }
    )


@router.post("/samples/import/email/preview", dependencies=guarded(Permission.EDIT_RECORDS))
async def sample_import_email_preview(
    request: Request,
    service: SamsService = Depends(get_service),
):
    """Render the confirmation e-mail for a completed import.

    Purely a render: nothing is sent here. The operator sees exactly what
    would go out and decides. An optional ``template`` code overrides the
    language-based pick, so the operator can switch template before sending.
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "Malformed request payload."}, status_code=400)

    user_nr = payload.get("user_nr")
    submitter = service.repo.get_submitter(int(user_nr)) if user_nr else None
    if submitter is None:
        return JSONResponse({"detail": "Submitter not found."}, status_code=404)

    store = EmailSettingsStore(service.setup_store)
    settings = store.load()
    language = getattr(submitter, "language", None)
    template_code, template_reason = store.resolve_template_code(
        language, payload.get("template")
    )
    template = store.template_for_language(language, template_code)
    message = build_confirmation(
        template=template,
        settings=settings,
        submitter=submitter,
        project_nr=int(payload.get("project_nr") or 0),
        project_name=str(payload.get("project_name") or ""),
        sample_nrs=[int(n) for n in (payload.get("sample_nrs") or [])],
        sample_labels=[str(s) for s in (payload.get("sample_labels") or [])],
    )
    return JSONResponse(
        {
            "email": message.as_dict(),
            "configured": store.is_configured(),
            "language": (language or "").strip(),
            "template": template_code,
            "template_reason": template_reason,
            "templates": store.template_choices(),
        }
    )


@router.post("/samples/import/email/send", dependencies=guarded(Permission.EDIT_RECORDS))
async def sample_import_email_send(
    request: Request,
    service: SamsService = Depends(get_service),
):
    """Send the confirmation e-mail the operator just reviewed.

    Takes the *edited* subject/body and the recipients straight from the
    request, so what the operator saw is what goes out: the To address,
    and the Cc / Bcc lists as they left them (Setup's copies ticked or
    unticked, plus any address added for this e-mail only).
    """
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "Malformed request payload."}, status_code=400)

    store = EmailSettingsStore(service.setup_store)
    settings = store.load()

    from sams_web.sample_import.mailer import RenderedEmail, split_addresses

    to = split_addresses(payload.get("to_address"))
    cc = split_addresses(payload.get("cc"))
    bcc = split_addresses(payload.get("bcc"))
    message = RenderedEmail(
        to_address=", ".join(to),
        subject=str(payload.get("subject") or ""),
        body=str(payload.get("body") or ""),
        from_address=str(settings.get("from_address") or ""),
        from_name=str(settings.get("from_name") or ""),
        reply_to=str(settings.get("reply_to") or ""),
        cc=", ".join(cc),
        bcc=", ".join(bcc),
    )
    try:
        send_email(message, settings)
    except EmailError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected failure sending confirmation e-mail")
        return JSONResponse(
            {"detail": "The e-mail could not be sent. The import itself is unaffected."},
            status_code=500,
        )
    return JSONResponse({"sent": True, "to_address": message.to_address, "cc": cc, "bcc": bcc})

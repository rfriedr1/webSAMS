"""Dashboard, setup, and help page routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse

from sams_web.dependencies import get_service
from sams_web.services import SamsService
from sams_web.import_settings import (
    EMAIL_SERVER_FIELDS,
    EmailSettingsStore,
    stored_password_applies,
)
from sams_web.sample_import.mailer import EmailError, RenderedEmail, send_email
from sams_web.setup_handlers import handler_for
from sams_web.setup_sections import SETUP_SECTION_MAP
from sams_web.thresholds import STANDARD_LABELS

from sams_web.magic_nav import build_magic_nav_rules
from sams_web.routers.pages_shared import templates

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/")
def dashboard(
    request: Request,
    show_on_hold: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_dashboard(show_on_hold=show_on_hold)
    counts = data["counts"]
    standards = data["standards"]
    standard_statuses = data["standard_statuses"]
    chart_spec = [
        ("Planned", "planned"),
        ("In Prep", "in_prep"),
        ("Waiting for Graph", "waiting_for_graph"),
        ("Waiting for Meas", "waiting_for_meas"),
        ("Express", "waiting_express"),
    ]
    standards_spec = STANDARD_LABELS
    max_count = max(max(counts.values(), default=0), 1)
    queue_chart = [
        {
            "label": label,
            "key": key,
            "value": counts.get(key, 0),
            "pct": round((counts.get(key, 0) / max_count) * 100, 1),
        }
        for label, key in chart_spec
    ]
    standards_thresholds = data["standard_thresholds"]

    def _format_threshold_rule(rule: dict[str, int]) -> str:
        """Compact human description of a standard's threshold rule, shown
        as a hover tooltip on the dashboard standards-card. Mirrors the
        language of the Setup → Standard Inventory Thresholds editor so
        the user's mental model lines up across the two surfaces."""
        if not rule:
            return ""
        return (
            f"Red below {rule['red_below']}"
            f" · Yellow {rule['yellow_min']}–{rule['yellow_max']}"
            f" · Green above {rule['green_above']}"
        )

    standards_cards = [
        {
            "label": label,
            "key": key,
            "value": standards.get(key, 0),
            "status": standard_statuses.get(key, "neutral"),
            "rule_summary": _format_threshold_rule(standards_thresholds.get(key, {})),
        }
        for label, key in standards_spec
    ]
    max_standard_count = max(max(standards.values(), default=0), 1)
    standards_chart = [
        {
            **item,
            "pct": round((item["value"] / max_standard_count) * 100, 1),
        }
        for item in standards_cards
    ]
    return templates.TemplateResponse(request, "dashboard.html",
        {
            "request": request,
            "counts": counts,
            "tables": data["tables"],
            "queue_chart": queue_chart,
            "standards_cards": standards_cards,
            "standards_chart": standards_chart,
            "show_on_hold": show_on_hold,
        },
    )


@router.get("/setup")
def setup_page(
    request: Request,
    section: str | None = Query(default=None),
    saved: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    sections = service.list_setup_sections()
    try:
        active_section = service.get_setup_section(section)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return templates.TemplateResponse(request, "setup.html",
        {
            "request": request,
            "saved": saved,
            "error": None,
            "sections": sections,
            "active_section": active_section,
        },
    )


@router.get("/help")
def help_page(request: Request):
    return templates.TemplateResponse(request, "help.html",
        {
            "request": request,
            "magic_nav_rules": build_magic_nav_rules(),
        },
    )


@router.post("/setup/email/test")
async def setup_email_test(
    request: Request,
    service: SamsService = Depends(get_service),
):
    """Send a one-off test message so the operator can verify SMTP settings.

    Uses the values currently in the form rather than the saved ones, so
    settings can be checked *before* committing them. A blank password
    field falls back to the stored password, which lets the operator
    retest without retyping it.
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"detail": "Malformed request payload."}, status_code=400)

    to_address = str(body.get("to_address") or "").strip()
    if not to_address or "@" not in to_address:
        return JSONResponse(
            {"detail": "Enter the address the test should be sent to."}, status_code=400
        )

    store = EmailSettingsStore(service.setup_store)
    saved = store.load()
    settings: dict[str, Any] = {}
    for field in EMAIL_SERVER_FIELDS:
        # A field the form did not send at all falls back to the saved
        # value; one that was sent *empty* is honoured as empty. Blanking
        # the username to test an unauthenticated relay has to actually
        # drop the username, not silently reuse the stored one.
        settings[field.key] = (
            body[field.key] if field.key in body else saved.get(field.key, field.default)
        )
    # The password is the one exception: a blank box reuses the stored
    # secret — but ONLY when the connection target is the stored one.
    # Host, port, security and user all come from the request, so without
    # this check anyone who can reach the app could point the host at a
    # server they control and have SAMS log in there with the real mailbox
    # password.
    if not str(settings.get("smtp_password") or ""):
        if stored_password_applies(settings, saved):
            settings["smtp_password"] = saved.get("smtp_password", "")
        elif str(settings.get("smtp_user") or "").strip():
            return JSONResponse(
                {
                    "detail": (
                        "Enter the password for this server. The stored password is "
                        "only reused for the saved server, port, security mode and username."
                    )
                },
                status_code=400,
            )

    if not str(settings.get("smtp_host") or "").strip():
        return JSONResponse({"detail": "Set an SMTP server first."}, status_code=400)
    if not str(settings.get("from_address") or "").strip():
        return JSONResponse({"detail": "Set a From address first."}, status_code=400)

    message = RenderedEmail(
        to_address=to_address,
        subject="SAMS test e-mail",
        body=(
            "This is a test message from SAMS Web.\n\n"
            "If you are reading it, the outgoing mail settings under\n"
            "Setup -> E-mail are working.\n\n"
            f"Server:  {settings.get('smtp_host')}:{settings.get('smtp_port')} "
            f"({settings.get('smtp_security')})\n"
            f"From:    {settings.get('from_address')}\n"
            f"Sent to: {to_address}\n"
        ),
        from_address=str(settings.get("from_address") or ""),
        from_name=str(settings.get("from_name") or ""),
        reply_to=str(settings.get("reply_to") or ""),
        # Deliberately no Bcc: a connection test should not copy anyone.
        bcc="",
    )
    try:
        send_email(message, settings)
    except EmailError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected failure sending test e-mail")
        return JSONResponse(
            {"detail": "The test e-mail could not be sent."}, status_code=500
        )
    return JSONResponse({"sent": True, "to_address": to_address})


@router.post("/setup/{section_key}")
async def setup_section_submit(
    request: Request,
    section_key: str,
    service: SamsService = Depends(get_service),
):
    if section_key not in SETUP_SECTION_MAP:
        raise HTTPException(status_code=404, detail=f"Unknown setup section: {section_key}")
    handler = handler_for(section_key)
    payload = handler.read_form(await request.form())

    try:
        service.update_setup_section(section_key=section_key, payload=payload)
    except ValueError as exc:
        active_section = handler.keep_typed(service.get_setup_section(section_key), payload)
        return templates.TemplateResponse(request, "setup.html",
            {
                "request": request,
                "saved": False,
                "error": str(exc),
                "sections": service.list_setup_sections(),
                "active_section": active_section,
            },
            status_code=400,
        )

    return RedirectResponse(url=f"/setup?section={section_key}&saved=true", status_code=303)

"""Dashboard, setup, and help page routes."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from sams_web.access import Permission, guarded
from fastapi.responses import JSONResponse, RedirectResponse

from sams_web.ea_checks import EaCheckLog
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


# Queue labels in the dashboard's own words, keyed by the queue key used
# for both the counts and the tables (`SamsRepository.get_dashboard_*`).
DASHBOARD_QUEUE_LABELS: dict[str, str] = {
    "waiting_express": "Express",
    "planned": "Planned",
    "in_prep": "In prep",
    "waiting_for_graph": "Waiting for graph",
    "waiting_for_meas": "Waiting for meas",
}
# Bar order in the Lab queues panel: the sample's path through the lab,
# with Express (a priority flag, not a step) last.
DASHBOARD_QUEUE_BAR_ORDER = ("planned", "in_prep", "waiting_for_graph", "waiting_for_meas", "waiting_express")
# Columns a queue table needs only to build its links, never shown.
DASHBOARD_HELPER_COLUMNS = ("project_nr", "user_nr")
DASHBOARD_HELPER_COLUMNS_BY_QUEUE = {"waiting_for_meas": ("sample_nr", "prep_nr", "target_nr")}
# Visible note next to a standard whose stock is at or below its threshold.
STANDARD_STATUS_TAGS = {"critical": "Low", "warning": "Getting low"}
# Lab queue bars split each queue by its project's desired date.
DASHBOARD_DUE_SOON_DAYS = 14
DEADLINE_BANDS = ("late", "soon", "later", "undated")
DEADLINE_BAND_LABELS = {
    "late": "Past desired date",
    "soon": f"Due within {DASHBOARD_DUE_SOON_DAYS} days",
    "later": "Due later",
    "undated": "No desired date",
}
# Each queue's count is its table's rows, except Waiting for graph: its
# table lists one row per target, its count is per sample. The deadline
# split counts what the count counts.
DASHBOARD_QUEUE_UNIT = {"waiting_for_graph": "sample_nr"}


def queue_anchor(key: str) -> str:
    """Element id of a queue's table panel (`#tbl-planned`, …)."""
    return "tbl-" + key.replace("_", "-")


def _percent_of(value: int, maximum: int) -> float:
    return round((value / maximum) * 100, 1) if maximum > 0 else 0.0


def _format_threshold_rule(rule: dict[str, int]) -> str:
    """Compact description of a standard's threshold rule, shown as the
    hover text of its dashboard bar. Mirrors the language of Setup →
    Standard Inventory Thresholds."""
    if not rule:
        return ""
    return (
        f"Red below {rule['red_below']}"
        f" · Yellow {rule['yellow_min']}–{rule['yellow_max']}"
        f" · Green above {rule['green_above']}"
    )


def _standard_scale(value: int, rule: dict[str, int], max_standard: int) -> dict[str, Any]:
    """Bar geometry for one standard. A full bar means "enough": the scale
    ends at the first green count (`green_above + 1`), so 11 Oxas against
    a green threshold of 14 fill 73 % of the bar, not 100 % because they
    happen to be the largest stock. The red and yellow ranges are drawn as
    faint zones in the track. Without a rule the bar falls back to the
    largest stock, and there is no target to show."""
    if not rule:
        return {"pct": _percent_of(value, max_standard), "target": None, "zones": None}
    target = int(rule["green_above"]) + 1

    def at(count: int) -> float:
        return round(min(max(count, 0) / target, 1) * 100, 1)

    return {
        "pct": at(value),
        "target": target,
        "zones": {
            "red_end": at(int(rule["red_below"])),
            "yellow_start": at(int(rule["yellow_min"])),
            "yellow_end": at(int(rule["yellow_max"]) + 1),
        },
    }


def _as_date(value: Any) -> date | None:
    """A queue row's desired date as a `date`, or None when it is missing
    or a legacy sentinel (year < 1950)."""
    if isinstance(value, datetime):
        value = value.date()
    elif isinstance(value, str):
        try:
            value = date.fromisoformat(value.strip()[:10])
        except ValueError:
            return None
    if not isinstance(value, date) or value.year < 1950:
        return None
    return value


def deadline_split(key: str, rows: list[dict[str, Any]], today: date) -> dict[str, int]:
    """How many items of one queue are past their desired date, due within
    `DASHBOARD_DUE_SOON_DAYS`, due later, or have no desired date. Counts
    the same items as the queue's count (`DASHBOARD_QUEUE_UNIT`)."""
    unit = DASHBOARD_QUEUE_UNIT.get(key)
    soon_end = today + timedelta(days=DASHBOARD_DUE_SOON_DAYS)
    split = dict.fromkeys(DEADLINE_BANDS, 0)
    seen: set[Any] = set()
    for row in rows:
        ident = row.get(unit) if unit else None
        if ident is not None:
            if ident in seen:
                continue
            seen.add(ident)
        desired = _as_date(row.get("desired_date"))
        if desired is None:
            split["undated"] += 1
        elif desired < today:
            split["late"] += 1
        elif desired <= soon_end:
            split["soon"] += 1
        else:
            split["later"] += 1
    return split


def _queue_bar(key: str, count: int, rows: list[dict[str, Any]], today: date) -> dict[str, Any]:
    """One Lab queues bar. A queue has no natural maximum, so the bar is not
    a fill level: it is the whole queue, split by how urgent its items are.
    Only the queue's own count gives its size."""
    split = deadline_split(key, rows, today)
    total = sum(split.values())
    label = DASHBOARD_QUEUE_LABELS.get(key, key)
    segments = [
        {"band": band, "count": split[band], "pct": _percent_of(split[band], total)}
        for band in DEADLINE_BANDS
        if split[band]
    ]
    details = ", ".join(f"{split[band]} {DEADLINE_BAND_LABELS[band].lower()}" for band in DEADLINE_BANDS if split[band])
    return {
        "key": key,
        "label": label,
        "value": count,
        "late": split["late"],
        "segments": segments,
        "title": f"{label}: {count}" + (f" ({details})" if details else ""),
        "anchor": queue_anchor(key),
    }


def build_dashboard_view(data: dict[str, Any], today: date | None = None) -> dict[str, Any]:
    """Shape `SamsService.get_dashboard()` into what dashboard.html shows:
    queue bars, standard bars and one tab per queue table. Pure, so the
    page logic is testable without a database."""
    today = today or date.today()
    counts: dict[str, int] = data["counts"]
    standards: dict[str, int] = data["standards"]
    statuses: dict[str, str] = data["standard_statuses"]
    thresholds = data["standard_thresholds"]
    tables: dict[str, list[dict[str, Any]]] = data["tables"]

    queue_bars = [
        _queue_bar(key, counts.get(key, 0), tables.get(key) or [], today)
        for key in DASHBOARD_QUEUE_BAR_ORDER
    ]
    present_bands = {segment["band"] for bar in queue_bars for segment in bar["segments"]}
    deadline_legend = [
        {"band": band, "label": DEADLINE_BAND_LABELS[band]}
        for band in DEADLINE_BANDS
        if band in present_bands
    ]

    max_standard = max(standards.values(), default=0)
    standard_bars = []
    for label, key in STANDARD_LABELS:
        value = standards.get(key, 0)
        status = statuses.get(key, "neutral")
        rule = thresholds.get(key) or {}
        standard_bars.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "status": status,
                "tag": STANDARD_STATUS_TAGS.get(status, ""),
                "rule_summary": _format_threshold_rule(rule),
                **_standard_scale(value, rule, max_standard),
            }
        )

    queue_tabs = []
    for key, rows in tables.items():
        hidden = set(DASHBOARD_HELPER_COLUMNS) | set(DASHBOARD_HELPER_COLUMNS_BY_QUEUE.get(key, ()))
        columns = [column for column in (rows[0].keys() if rows else ()) if column not in hidden]
        queue_tabs.append(
            {
                "key": key,
                "label": DASHBOARD_QUEUE_LABELS.get(key, key.replace("_", " ").capitalize()),
                "anchor": queue_anchor(key),
                "rows": rows,
                "columns": columns,
            }
        )

    return {
        "queue_bars": queue_bars,
        "deadline_legend": deadline_legend,
        "due_soon_days": DASHBOARD_DUE_SOON_DAYS,
        "standard_bars": standard_bars,
        "standards_total": sum(standards.get(key, 0) for _label, key in STANDARD_LABELS),
        "queue_tabs": queue_tabs,
    }


@router.get("/")
def dashboard(
    request: Request,
    show_on_hold: bool = Query(default=False),
    service: SamsService = Depends(get_service),
):
    data = service.get_dashboard(show_on_hold=show_on_hold)
    return templates.TemplateResponse(request, "dashboard.html",
        {
            "request": request,
            **build_dashboard_view(data),
            "show_on_hold": show_on_hold,
            "ea_tile": EaCheckLog(service).dashboard_tile(),
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


@router.post("/setup/email/test", dependencies=guarded(Permission.MANAGE_SETUP))
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


@router.post("/setup/{section_key}", dependencies=guarded(Permission.MANAGE_SETUP))
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

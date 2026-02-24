"""Dashboard, setup, and help page routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from sams_web.dependencies import get_service
from sams_web.services import SamsService
from sams_web.setup_sections import (
    SETUP_SECTION_GRAPHITIZATION_SYSTEMS,
    SETUP_SECTION_STANDARD_THRESHOLDS,
)
from sams_web.thresholds import STANDARD_LABELS, THRESHOLD_FIELDS

from sams_web.routers.pages_shared import build_magic_nav_rules, build_threshold_rows, templates

router = APIRouter()


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
    standards_cards = [
        {
            "label": label,
            "key": key,
            "value": standards.get(key, 0),
            "status": standard_statuses.get(key, "neutral"),
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
    return templates.TemplateResponse(
        "dashboard.html",
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

    threshold_rows = None
    threshold_fields = None
    list_text = None
    if active_section["kind"] == "threshold_matrix":
        threshold_rows = build_threshold_rows(active_section["thresholds"])
        threshold_fields = active_section["threshold_fields"]
    elif active_section["kind"] == "string_list":
        list_text = active_section.get("list_text", "")

    return templates.TemplateResponse(
        "setup.html",
        {
            "request": request,
            "saved": saved,
            "error": None,
            "sections": sections,
            "active_section": active_section,
            "threshold_rows": threshold_rows,
            "threshold_fields": threshold_fields,
            "list_text": list_text,
        },
    )


@router.get("/help")
def help_page(request: Request):
    return templates.TemplateResponse(
        "help.html",
        {
            "request": request,
            "magic_nav_rules": build_magic_nav_rules(),
        },
    )


@router.post("/setup/{section_key}")
async def setup_section_submit(
    request: Request,
    section_key: str,
    service: SamsService = Depends(get_service),
):
    form = await request.form()
    payload: dict[str, Any] = {}
    if section_key == SETUP_SECTION_STANDARD_THRESHOLDS:
        for _, key in STANDARD_LABELS:
            payload[key] = {
                field: form.get(f"{key}_{field}")
                for field, _ in THRESHOLD_FIELDS
            }
    elif section_key == SETUP_SECTION_GRAPHITIZATION_SYSTEMS:
        raw_list_text = str(form.get("graphitization_systems_text") or "")
        payload["items"] = raw_list_text.splitlines()
        payload["raw_text"] = raw_list_text

    try:
        service.update_setup_section(section_key=section_key, payload=payload)
    except ValueError as exc:
        sections = service.list_setup_sections()
        try:
            active_section = service.get_setup_section(section_key)
        except ValueError as section_exc:
            raise HTTPException(status_code=404, detail=str(section_exc)) from section_exc

        threshold_rows = None
        threshold_fields = None
        list_text = None
        if active_section["kind"] == "threshold_matrix":
            threshold_rows = build_threshold_rows(payload if payload else active_section["thresholds"])
            threshold_fields = active_section["threshold_fields"]
        elif active_section["kind"] == "string_list":
            list_text = str(payload.get("raw_text") or active_section.get("list_text") or "")

        return templates.TemplateResponse(
            "setup.html",
            {
                "request": request,
                "saved": False,
                "error": str(exc),
                "sections": sections,
                "active_section": active_section,
                "threshold_rows": threshold_rows,
                "threshold_fields": threshold_fields,
                "list_text": list_text,
            },
            status_code=400,
        )

    from fastapi.responses import RedirectResponse  # local import to keep module imports light

    return RedirectResponse(url=f"/setup?section={section_key}&saved=true", status_code=303)

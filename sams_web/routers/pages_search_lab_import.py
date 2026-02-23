"""Search and lab operation page routes."""

from __future__ import annotations

import json
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.repositories import SEARCH_CONTEXTS
from sams_web.routers.pages_shared import parse_positive_int, templates
from sams_web.services import SamsService

router = APIRouter()

GRAPHITIZATION_SYSTEM_OPTIONS = (
    "mag",
    "age.1",
    "age.2",
    "age64.1",
    "age64.2",
    "autosampler",
)


def _build_lab_preparation_page_context(
    request: Request,
    *,
    service: SamsService,
    show_on_hold: bool,
    bench_sample_nr_raw: str = "",
    bench_prep_nr_raw: str = "",
    bench_form_values: dict[str, str] | None = None,
    bench_field_errors: dict[str, str] | None = None,
    bench_error: str | None = None,
    bench_saved: bool = False,
    bench_notice: str | None = None,
) -> dict[str, object]:
    data = service.get_dashboard(show_on_hold=show_on_hold)
    rows = data["tables"].get("planned", [])

    bench_form_values = bench_form_values or {}
    bench_field_errors = bench_field_errors or {}
    if not bench_sample_nr_raw and rows:
        first_row = rows[0]
        first_sample = first_row.get("sample_nr")
        first_prep = first_row.get("prep_nr")
        if first_sample is not None:
            bench_sample_nr_raw = str(first_sample)
        if first_prep is not None:
            bench_prep_nr_raw = str(first_prep)
    bench_sample_nr = parse_positive_int(bench_sample_nr_raw) if bench_sample_nr_raw else None
    bench_prep_nr = parse_positive_int(bench_prep_nr_raw) if bench_prep_nr_raw else None

    bench_entry = None
    if bench_sample_nr is not None:
        bench_entry = service.get_preparation_bench_entry(bench_sample_nr, prep_nr=bench_prep_nr)
        if bench_entry is None and bench_error is None:
            bench_error = "Sample or preparation was not found for bench entry."
        elif bench_entry is not None:
            bench_prep_nr_raw = str(bench_entry["preparation"].prep_nr)

    return {
        "request": request,
        "title": "Preparation Workflow",
        "description": "Preparation worklist for samples that are ready for pre-treatment planning and execution.",
        "table_key": "planned",
        "table_title": "Planned",
        "rows": rows,
        "show_on_hold": show_on_hold,
        "show_on_hold_enabled": True,
        "bench_entry_enabled": True,
        "bench_entry": bench_entry,
        "bench_sample_nr_query": bench_sample_nr_raw,
        "bench_prep_nr_query": bench_prep_nr_raw,
        "bench_form_values": bench_form_values,
        "bench_field_errors": bench_field_errors,
        "bench_error": bench_error,
        "bench_saved": bench_saved,
        "bench_notice": bench_notice,
        "bench_method_options": service.list_preparation_methods(),
    }


def _build_lab_graphitization_page_context(
    request: Request,
    *,
    service: SamsService,
    graph_sample_nr_raw: str = "",
    graph_prep_nr_raw: str = "",
    graph_target_nr_raw: str = "",
    graph_form_values: dict[str, str] | None = None,
    graph_field_errors: dict[str, str] | None = None,
    graph_error: str | None = None,
    graph_saved: bool = False,
    graph_notice: str | None = None,
    graph_batch_notice: str | None = None,
    graph_batch_error: str | None = None,
) -> dict[str, object]:
    data = service.get_dashboard(show_on_hold=False)
    rows = data["tables"].get("waiting_for_graph", [])

    graph_form_values = graph_form_values or {}
    graph_field_errors = graph_field_errors or {}
    if not graph_sample_nr_raw and rows:
        first_row = rows[0]
        if first_row.get("sample_nr") is not None:
            graph_sample_nr_raw = str(first_row.get("sample_nr"))
        if first_row.get("prep_nr") is not None:
            graph_prep_nr_raw = str(first_row.get("prep_nr"))
        if first_row.get("target_nr") is not None:
            graph_target_nr_raw = str(first_row.get("target_nr"))

    graph_sample_nr = parse_positive_int(graph_sample_nr_raw) if graph_sample_nr_raw else None
    graph_prep_nr = parse_positive_int(graph_prep_nr_raw) if graph_prep_nr_raw else None
    graph_target_nr = parse_positive_int(graph_target_nr_raw) if graph_target_nr_raw else None

    graph_bench_entry = None
    if graph_sample_nr is not None:
        graph_bench_entry = service.get_graphitization_bench_entry(
            graph_sample_nr,
            prep_nr=graph_prep_nr,
            target_nr=graph_target_nr,
        )
        if graph_bench_entry is None and graph_error is None:
            graph_error = "Sample / preparation / target was not found for graphitization bench entry."
        elif graph_bench_entry is not None:
            graph_prep_nr_raw = str(graph_bench_entry["preparation"].prep_nr)
            graph_target_nr_raw = str(graph_bench_entry["target"].target_nr)

    return {
        "request": request,
        "title": "Graphitization Workflow",
        "description": "Graphitization worklist for samples waiting to enter target production.",
        "table_key": "waiting_for_graph",
        "table_title": "Waiting For Graph",
        "rows": rows,
        "show_on_hold": False,
        "show_on_hold_enabled": False,
        "graph_bench_entry_enabled": True,
        "graph_bench_entry": graph_bench_entry,
        "graph_sample_nr_query": graph_sample_nr_raw,
        "graph_prep_nr_query": graph_prep_nr_raw,
        "graph_target_nr_query": graph_target_nr_raw,
        "graph_form_values": graph_form_values,
        "graph_field_errors": graph_field_errors,
        "graph_error": graph_error,
        "graph_saved": graph_saved,
        "graph_notice": graph_notice,
        "graph_batch_notice": graph_batch_notice,
        "graph_batch_error": graph_batch_error,
        "graph_batch_system_options": GRAPHITIZATION_SYSTEM_OPTIONS,
    }


@router.get("/search")
def search_page(
    request: Request,
    context: str = Query(default="samples"),
    phrase: str = Query(default=""),
    service: SamsService = Depends(get_service),
):
    results: list[dict[str, object]] = []
    error: str | None = None
    global_mode = request.query_params.get("global") == "1"
    context_param_present = request.query_params.get("context") is not None
    auto_load = (not global_mode) and context_param_present
    if phrase.strip() or auto_load:
        try:
            results = service.search(context=context, phrase=phrase.strip())
        except ValueError as exc:
            error = str(exc)

    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "contexts": list(SEARCH_CONTEXTS.keys()),
            "context": context,
            "phrase": phrase,
            "results": results,
            "error": error,
            "auto_load": auto_load,
            "global_mode": global_mode,
        },
    )


@router.get("/lab/preparation")
def lab_preparation_page(
    request: Request,
    show_on_hold: bool = Query(default=False),
    bench_sample_nr: str = Query(default=""),
    bench_prep_nr: str = Query(default=""),
    bench_saved: bool = Query(default=False),
    bench_notice: str = Query(default=""),
    service: SamsService = Depends(get_service),
):
    return templates.TemplateResponse(
        "lab_queue.html",
        _build_lab_preparation_page_context(
            request,
            service=service,
            show_on_hold=show_on_hold,
            bench_sample_nr_raw=bench_sample_nr.strip(),
            bench_prep_nr_raw=bench_prep_nr.strip(),
            bench_saved=bench_saved,
            bench_notice=bench_notice.strip() or None,
        ),
    )


@router.post("/lab/preparation/bench/save")
async def lab_preparation_bench_save(
    request: Request,
    service: SamsService = Depends(get_service),
):
    form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key in form.keys():
        values = form.getlist(key)
        value = values[-1] if values else ""
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    bench_sample_nr_raw = (submitted_fields.get("bench__sample_nr") or "").strip()
    bench_prep_nr_raw = (submitted_fields.get("bench__prep_nr") or "").strip()
    action = (submitted_fields.get("bench__action") or "save").strip().lower()
    show_on_hold = (submitted_fields.get("bench__show_on_hold") or "").strip().lower() in {"1", "true", "yes", "on"}

    bench_sample_nr = parse_positive_int(bench_sample_nr_raw)
    bench_prep_nr = parse_positive_int(bench_prep_nr_raw)
    if bench_sample_nr is None or bench_prep_nr is None:
        return templates.TemplateResponse(
            "lab_queue.html",
            _build_lab_preparation_page_context(
                request,
                service=service,
                show_on_hold=show_on_hold,
                bench_sample_nr_raw=bench_sample_nr_raw,
                bench_prep_nr_raw=bench_prep_nr_raw,
                bench_form_values=submitted_fields,
                bench_error="Sample # and Prep # are required to save bench entry data.",
            ),
            status_code=422,
        )

    next_entry: tuple[int, int] | None = None
    if action == "save_next":
        next_entry = service.get_next_planned_bench_entry(
            bench_sample_nr,
            bench_prep_nr,
            show_on_hold=show_on_hold,
        )

    saved, field_errors, save_error = service.update_preparation_bench_entry(
        bench_sample_nr,
        bench_prep_nr,
        submitted_fields,
    )
    if not saved:
        return templates.TemplateResponse(
            "lab_queue.html",
            _build_lab_preparation_page_context(
                request,
                service=service,
                show_on_hold=show_on_hold,
                bench_sample_nr_raw=bench_sample_nr_raw,
                bench_prep_nr_raw=bench_prep_nr_raw,
                bench_form_values=submitted_fields,
                bench_field_errors=field_errors,
                bench_error=save_error,
            ),
            status_code=422,
        )

    query_parts = [f"show_on_hold={'true' if show_on_hold else 'false'}", "bench_saved=true"]
    if action == "save_next" and next_entry is not None:
        query_parts.append(f"bench_sample_nr={next_entry[0]}")
        query_parts.append(f"bench_prep_nr={next_entry[1]}")
        query_parts.append("bench_notice=Saved+and+loaded+next+planned+sample.")
    else:
        query_parts.append(f"bench_sample_nr={bench_sample_nr}")
        query_parts.append(f"bench_prep_nr={bench_prep_nr}")
        if action == "save_next":
            query_parts.append("bench_notice=Saved.+No+next+planned+sample+was+found.")
    return RedirectResponse(url=f"/lab/preparation?{'&'.join(query_parts)}", status_code=303)


@router.get("/lab/graphitization")
def lab_graphitization_page(
    request: Request,
    graph_sample_nr: str = Query(default=""),
    graph_prep_nr: str = Query(default=""),
    graph_target_nr: str = Query(default=""),
    graph_saved: bool = Query(default=False),
    graph_notice: str = Query(default=""),
    graph_batch_notice: str = Query(default=""),
    graph_batch_error: str = Query(default=""),
    service: SamsService = Depends(get_service),
):
    return templates.TemplateResponse(
        "lab_queue.html",
        _build_lab_graphitization_page_context(
            request,
            service=service,
            graph_sample_nr_raw=graph_sample_nr.strip(),
            graph_prep_nr_raw=graph_prep_nr.strip(),
            graph_target_nr_raw=graph_target_nr.strip(),
            graph_saved=graph_saved,
            graph_notice=graph_notice.strip() or None,
            graph_batch_notice=graph_batch_notice.strip() or None,
            graph_batch_error=graph_batch_error.strip() or None,
        ),
    )


@router.post("/lab/graphitization/bench/save")
async def lab_graphitization_bench_save(
    request: Request,
    service: SamsService = Depends(get_service),
):
    form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key in form.keys():
        values = form.getlist(key)
        value = values[-1] if values else ""
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    graph_sample_nr_raw = (submitted_fields.get("graphbench__sample_nr") or "").strip()
    graph_prep_nr_raw = (submitted_fields.get("graphbench__prep_nr") or "").strip()
    graph_target_nr_raw = (submitted_fields.get("graphbench__target_nr") or "").strip()
    action = (submitted_fields.get("graphbench__action") or "save").strip().lower()

    graph_sample_nr = parse_positive_int(graph_sample_nr_raw)
    graph_prep_nr = parse_positive_int(graph_prep_nr_raw)
    graph_target_nr = parse_positive_int(graph_target_nr_raw)
    if graph_sample_nr is None or graph_prep_nr is None or graph_target_nr is None:
        return templates.TemplateResponse(
            "lab_queue.html",
            _build_lab_graphitization_page_context(
                request,
                service=service,
                graph_sample_nr_raw=graph_sample_nr_raw,
                graph_prep_nr_raw=graph_prep_nr_raw,
                graph_target_nr_raw=graph_target_nr_raw,
                graph_form_values=submitted_fields,
                graph_error="Sample #, Prep # and Target # are required to save graphitization bench data.",
            ),
            status_code=422,
        )

    next_entry: tuple[int, int, int] | None = None
    if action == "save_next":
        next_entry = service.get_next_graphitization_bench_entry(
            graph_sample_nr,
            graph_prep_nr,
            graph_target_nr,
        )

    saved, field_errors, save_error = service.update_graphitization_bench_entry(
        graph_sample_nr,
        graph_prep_nr,
        graph_target_nr,
        submitted_fields,
    )
    if not saved:
        return templates.TemplateResponse(
            "lab_queue.html",
            _build_lab_graphitization_page_context(
                request,
                service=service,
                graph_sample_nr_raw=graph_sample_nr_raw,
                graph_prep_nr_raw=graph_prep_nr_raw,
                graph_target_nr_raw=graph_target_nr_raw,
                graph_form_values=submitted_fields,
                graph_field_errors=field_errors,
                graph_error=save_error,
            ),
            status_code=422,
        )

    query_parts = ["graph_saved=true"]
    if action == "save_next" and next_entry is not None:
        query_parts.extend(
            [
                f"graph_sample_nr={next_entry[0]}",
                f"graph_prep_nr={next_entry[1]}",
                f"graph_target_nr={next_entry[2]}",
                "graph_notice=Saved+and+loaded+next+waiting-for-graph+target.",
            ]
        )
    else:
        query_parts.extend(
            [
                f"graph_sample_nr={graph_sample_nr}",
                f"graph_prep_nr={graph_prep_nr}",
                f"graph_target_nr={graph_target_nr}",
            ]
        )
        if action == "save_next":
            query_parts.append("graph_notice=Saved.+No+next+waiting-for-graph+target+was+found.")
    return RedirectResponse(url=f"/lab/graphitization?{'&'.join(query_parts)}", status_code=303)


@router.post("/lab/graphitization/bench/save-batch")
async def lab_graphitization_bench_save_batch(
    request: Request,
    service: SamsService = Depends(get_service),
):
    form = await request.form()
    submitted_fields: dict[str, str] = {}
    for key in form.keys():
        values = form.getlist(key)
        value = values[-1] if values else ""
        submitted_fields[key] = value if isinstance(value, str) else str(value)

    graph_sample_nr_raw = (submitted_fields.get("graphbatch__sample_nr") or "").strip()
    graph_prep_nr_raw = (submitted_fields.get("graphbatch__prep_nr") or "").strip()
    graph_target_nr_raw = (submitted_fields.get("graphbatch__target_nr") or "").strip()
    batch_name = (submitted_fields.get("graphbatch__batch_name") or "").strip()
    targets_json = (submitted_fields.get("graphbatch__targets_json") or "").strip()

    target_keys: list[tuple[int, int, int]] = []
    try:
        raw_items = json.loads(targets_json) if targets_json else []
        if not isinstance(raw_items, list):
            raw_items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            sample_nr = parse_positive_int(str(item.get("sample_nr", "")))
            prep_nr = parse_positive_int(str(item.get("prep_nr", "")))
            target_nr = parse_positive_int(str(item.get("target_nr", "")))
            if sample_nr is None or prep_nr is None or target_nr is None:
                continue
            target_keys.append((sample_nr, prep_nr, target_nr))
    except json.JSONDecodeError:
        target_keys = []

    saved, error_message = service.save_graph_batch_assignments(
        batch_name=batch_name,
        target_keys=target_keys,
    )
    query_parts = []
    if graph_sample_nr_raw:
        query_parts.append(f"graph_sample_nr={graph_sample_nr_raw}")
    if graph_prep_nr_raw:
        query_parts.append(f"graph_prep_nr={graph_prep_nr_raw}")
    if graph_target_nr_raw:
        query_parts.append(f"graph_target_nr={graph_target_nr_raw}")
    if saved:
        query_parts.append("graph_batch_notice=Graph+batch+saved.")
        query_parts.append("graph_batch_saved=true")
    else:
        query_parts.append(f"graph_batch_error={quote_plus(error_message or 'Unable to save graph batch.')}")
    suffix = f"?{'&'.join(query_parts)}" if query_parts else ""
    return RedirectResponse(url=f"/lab/graphitization{suffix}", status_code=303)


@router.get("/lab/analysis")
def lab_analysis_page(
    request: Request,
    magazine: str = Query(default=""),
    service: SamsService = Depends(get_service),
):
    data = service.get_dashboard(show_on_hold=False)
    rows = data["tables"].get("waiting_for_meas", [])
    magazine_query = magazine.strip()
    magazine_options = service.list_magazines()
    magazine_error: str | None = None
    magazine_rows: list[dict[str, object]] = []
    if magazine_query:
        resolved_magazine = service.resolve_existing_magazine(magazine_query)
        if resolved_magazine is None:
            magazine_error = "Magazine not found. Please choose an existing magazine."
        else:
            magazine_query = resolved_magazine
            magazine_rows = service.list_targets_by_magazine(resolved_magazine)
    return templates.TemplateResponse(
        "lab_queue.html",
        {
            "request": request,
            "title": "Analysis Workflow",
            "description": "Analysis worklist for samples waiting for measurement and result review.",
            "table_key": "waiting_for_meas",
            "table_title": "Waiting For Meas",
            "rows": rows,
            "show_on_hold": False,
            "show_on_hold_enabled": False,
            "magazine_lookup_enabled": True,
            "magazine_query": magazine_query,
            "magazine_table_columns": (
                "position",
                "sample_nr",
                "prep_nr",
                "target_nr",
                "user_label",
                "project",
                "user_last_name",
            ),
            "magazine_options": magazine_options,
            "magazine_error": magazine_error,
            "magazine_rows": magazine_rows,
        },
    )

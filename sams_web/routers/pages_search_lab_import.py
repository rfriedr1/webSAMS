"""Search and lab operation page routes."""

from __future__ import annotations

import json
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse

from sams_web.dependencies import get_service
from sams_web.graphitization_bench import GraphitizationBench
from sams_web.preparation_bench import PreparationBench
from sams_web.search import SEARCH_CONTEXTS
from sams_web.routers.pages_shared import parse_positive_int, templates
from sams_web.services import SamsService

router = APIRouter()


def _form_to_dict(form) -> dict[str, str]:
    submitted: dict[str, str] = {}
    for key in form.keys():
        values = form.getlist(key)
        value = values[-1] if values else ""
        submitted[key] = value if isinstance(value, str) else str(value)
    return submitted


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _build_prep_redirect(
    *,
    sample_nr: int,
    prep_nr: int,
    show_on_hold: bool,
    action: str,
    next_cursor: tuple[int, ...] | None,
) -> str:
    parts = [f"show_on_hold={'true' if show_on_hold else 'false'}", "bench_saved=true"]
    if action == "save_next" and next_cursor is not None:
        parts.append(f"bench_sample_nr={next_cursor[0]}")
        parts.append(f"bench_prep_nr={next_cursor[1]}")
        parts.append("bench_notice=Saved+and+loaded+next+planned+sample.")
    else:
        parts.append(f"bench_sample_nr={sample_nr}")
        parts.append(f"bench_prep_nr={prep_nr}")
        if action == "save_next":
            parts.append("bench_notice=Saved.+No+next+planned+sample+was+found.")
    return "/lab/preparation?" + "&".join(parts)


def _build_graph_redirect(
    *,
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    action: str,
    next_cursor: tuple[int, ...] | None,
) -> str:
    parts = ["graph_saved=true"]
    if action == "save_next" and next_cursor is not None:
        parts.extend(
            [
                f"graph_sample_nr={next_cursor[0]}",
                f"graph_prep_nr={next_cursor[1]}",
                f"graph_target_nr={next_cursor[2]}",
                "graph_notice=Saved+and+loaded+next+waiting-for-graph+target.",
            ]
        )
    else:
        parts.extend(
            [
                f"graph_sample_nr={sample_nr}",
                f"graph_prep_nr={prep_nr}",
                f"graph_target_nr={target_nr}",
            ]
        )
        if action == "save_next":
            parts.append("graph_notice=Saved.+No+next+waiting-for-graph+target+was+found.")
    return "/lab/graphitization?" + "&".join(parts)


# ---- Search route ---------------------------------------------------------


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

    resolved_context = SEARCH_CONTEXTS.get(context)
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "contexts": list(SEARCH_CONTEXTS.keys()),
            "context": context,
            "resolved_context": resolved_context,
            "phrase": phrase,
            "results": results,
            "error": error,
            "auto_load": auto_load,
            "global_mode": global_mode,
        },
    )


# ---- Preparation bench routes ---------------------------------------------


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
    bench = PreparationBench(service)
    context = bench.page_view(
        show_on_hold=show_on_hold,
        sample_nr_raw=bench_sample_nr.strip(),
        prep_nr_raw=bench_prep_nr.strip(),
        saved=bench_saved,
        notice=bench_notice.strip() or None,
    )
    context["request"] = request
    return templates.TemplateResponse("lab_queue.html", context)


@router.post("/lab/preparation/bench/save")
async def lab_preparation_bench_save(
    request: Request,
    service: SamsService = Depends(get_service),
):
    submitted = _form_to_dict(await request.form())
    bench = PreparationBench(service)

    sample_nr_raw = (submitted.get("bench__sample_nr") or "").strip()
    prep_nr_raw = (submitted.get("bench__prep_nr") or "").strip()
    action = (submitted.get("bench__action") or "save").strip().lower()
    show_on_hold = _truthy(submitted.get("bench__show_on_hold"))

    sample_nr = parse_positive_int(sample_nr_raw)
    prep_nr = parse_positive_int(prep_nr_raw)
    if sample_nr is None or prep_nr is None:
        context = bench.page_view(
            show_on_hold=show_on_hold,
            sample_nr_raw=sample_nr_raw,
            prep_nr_raw=prep_nr_raw,
            form_values=submitted,
            error="Sample # and Prep # are required to save bench entry data.",
        )
        context["request"] = request
        return templates.TemplateResponse("lab_queue.html", context, status_code=422)

    outcome = bench.save(
        form_data=submitted,
        sample_nr=sample_nr,
        prep_nr=prep_nr,
        action=action,
        show_on_hold=show_on_hold,
    )
    if not outcome.success:
        context = bench.page_view(
            show_on_hold=show_on_hold,
            sample_nr_raw=sample_nr_raw,
            prep_nr_raw=prep_nr_raw,
            form_values=submitted,
            field_errors=outcome.field_errors,
            error=outcome.save_error,
        )
        context["request"] = request
        return templates.TemplateResponse("lab_queue.html", context, status_code=422)

    return RedirectResponse(
        _build_prep_redirect(
            sample_nr=sample_nr,
            prep_nr=prep_nr,
            show_on_hold=show_on_hold,
            action=action,
            next_cursor=outcome.next_cursor,
        ),
        status_code=303,
    )


# ---- Graphitization bench routes ------------------------------------------


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
    bench = GraphitizationBench(service)
    context = bench.page_view(
        sample_nr_raw=graph_sample_nr.strip(),
        prep_nr_raw=graph_prep_nr.strip(),
        target_nr_raw=graph_target_nr.strip(),
        saved=graph_saved,
        notice=graph_notice.strip() or None,
        batch_notice=graph_batch_notice.strip() or None,
        batch_error=graph_batch_error.strip() or None,
    )
    context["request"] = request
    return templates.TemplateResponse("lab_queue.html", context)


@router.post("/lab/graphitization/bench/save")
async def lab_graphitization_bench_save(
    request: Request,
    service: SamsService = Depends(get_service),
):
    submitted = _form_to_dict(await request.form())
    bench = GraphitizationBench(service)

    sample_nr_raw = (submitted.get("graphbench__sample_nr") or "").strip()
    prep_nr_raw = (submitted.get("graphbench__prep_nr") or "").strip()
    target_nr_raw = (submitted.get("graphbench__target_nr") or "").strip()
    action = (submitted.get("graphbench__action") or "save").strip().lower()

    sample_nr = parse_positive_int(sample_nr_raw)
    prep_nr = parse_positive_int(prep_nr_raw)
    target_nr = parse_positive_int(target_nr_raw)
    if sample_nr is None or prep_nr is None or target_nr is None:
        context = bench.page_view(
            sample_nr_raw=sample_nr_raw,
            prep_nr_raw=prep_nr_raw,
            target_nr_raw=target_nr_raw,
            form_values=submitted,
            error="Sample #, Prep # and Target # are required to save graphitization bench data.",
        )
        context["request"] = request
        return templates.TemplateResponse("lab_queue.html", context, status_code=422)

    outcome = bench.save(
        form_data=submitted,
        sample_nr=sample_nr,
        prep_nr=prep_nr,
        target_nr=target_nr,
        action=action,
    )
    if not outcome.success:
        context = bench.page_view(
            sample_nr_raw=sample_nr_raw,
            prep_nr_raw=prep_nr_raw,
            target_nr_raw=target_nr_raw,
            form_values=submitted,
            field_errors=outcome.field_errors,
            error=outcome.save_error,
        )
        context["request"] = request
        return templates.TemplateResponse("lab_queue.html", context, status_code=422)

    return RedirectResponse(
        _build_graph_redirect(
            sample_nr=sample_nr,
            prep_nr=prep_nr,
            target_nr=target_nr,
            action=action,
            next_cursor=outcome.next_cursor,
        ),
        status_code=303,
    )


@router.post("/lab/graphitization/bench/save-batch")
async def lab_graphitization_bench_save_batch(
    request: Request,
    service: SamsService = Depends(get_service),
):
    submitted = _form_to_dict(await request.form())
    bench = GraphitizationBench(service)

    sample_nr_raw = (submitted.get("graphbatch__sample_nr") or "").strip()
    prep_nr_raw = (submitted.get("graphbatch__prep_nr") or "").strip()
    target_nr_raw = (submitted.get("graphbatch__target_nr") or "").strip()
    batch_name = (submitted.get("graphbatch__batch_name") or "").strip()
    targets_json = (submitted.get("graphbatch__targets_json") or "").strip()

    target_keys: list[tuple[int, int, int]] = []
    try:
        raw_items = json.loads(targets_json) if targets_json else []
        if not isinstance(raw_items, list):
            raw_items = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            s = parse_positive_int(str(item.get("sample_nr", "")))
            p = parse_positive_int(str(item.get("prep_nr", "")))
            t = parse_positive_int(str(item.get("target_nr", "")))
            if s is None or p is None or t is None:
                continue
            target_keys.append((s, p, t))
    except json.JSONDecodeError:
        target_keys = []

    outcome = bench.assign_graph_batch(batch_name=batch_name, target_keys=target_keys)

    parts: list[str] = []
    if sample_nr_raw:
        parts.append(f"graph_sample_nr={sample_nr_raw}")
    if prep_nr_raw:
        parts.append(f"graph_prep_nr={prep_nr_raw}")
    if target_nr_raw:
        parts.append(f"graph_target_nr={target_nr_raw}")
    if outcome.success:
        parts.append("graph_batch_notice=Graph+batch+saved.")
        parts.append("graph_batch_saved=true")
    else:
        parts.append(
            f"graph_batch_error={quote_plus(outcome.error or 'Unable to save graph batch.')}"
        )
    suffix = f"?{'&'.join(parts)}" if parts else ""
    return RedirectResponse(url=f"/lab/graphitization{suffix}", status_code=303)


# ---- Analysis page (read-only; no bench yet) ------------------------------


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

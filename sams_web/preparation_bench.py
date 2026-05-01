"""Preparation bench: workflow module owning the prep bench page + save.

Replaces the per-bench logic that previously spread across `services.py`
(`get_preparation_bench_entry`, `get_next_planned_bench_entry`,
`update_preparation_bench_entry`, `_calculate_bench_yield`) and the
`_build_lab_preparation_page_context` builder in
`routers/pages_search_lab_import.py`.

The class exposes two operations to the route layer:

- `page_view(...)` returns the lab_queue.html context dict (without the
  FastAPI `request`, which the router merges in).
- `save(...)` applies a form submit and returns a `BenchSaveOutcome` whose
  `next_cursor` is populated only when the submit was a "save_next" and a
  next queue entry exists.

The bench-specific chemistry (weight_end derivation, auto prep_start /
prep_end stamping, prep_end-after-prep_start validation) lives as three
small named functions that `save()` runs in order over the staged
`prep_updates` dict.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, TYPE_CHECKING

from sams_web.bench_helpers import (
    BenchSaveOutcome,
    next_queue_entry,
    queue_tuples,
    select_preparation,
)
from sams_web.detail_update import coerce_column_value, model_columns
from sams_web.models import Preparation, Sample

if TYPE_CHECKING:
    from sams_web.services import SamsService


_FORM_PREFIX = "bench__"
_RESERVED_FORM_KEYS = frozenset({"sample_nr", "prep_nr", "action", "show_on_hold"})

_PREP_FIELDS: frozenset[str] = frozenset({
    "weight_start",
    "prep_start",
    "weight_medium",
    "weight_medium_2",
    "weight_end",
    "prep_end",
    "step1_method",
    "step2_method",
    "step3_method",
    "step4_method",
    "step5_method",
    "stop",
    "prep_comment",
})
_SAMPLE_FIELDS: frozenset[str] = frozenset({"s_no_leftover", "s_storage_loc"})
_METHOD_FIELDS: frozenset[str] = frozenset(
    {"step1_method", "step2_method", "step3_method", "step4_method", "step5_method"}
)


# ---- Bench-specific chemistry rules --------------------------------------


def _derive_weight_end(prep_updates: dict[str, Any], preparation: Preparation) -> dict[str, Any]:
    """If the operator hasn't supplied `weight_end` but both intermediate
    weights are known, derive it: `weight_end = weight_medium - weight_medium_2`.

    The two intermediate weights are the wet vial-with-sample and the
    dry vial weight; their difference is the dry sample mass.
    """
    effective_end = prep_updates.get("weight_end", preparation.weight_end)
    if "weight_end" in prep_updates and effective_end is not None:
        return prep_updates
    medium = prep_updates.get("weight_medium", preparation.weight_medium)
    medium_2 = prep_updates.get("weight_medium_2", preparation.weight_medium_2)
    if medium is None or medium_2 is None:
        return prep_updates
    try:
        derived = float(Decimal(str(medium)) - Decimal(str(medium_2)))
    except (InvalidOperation, ValueError):
        return prep_updates
    revised = dict(prep_updates)
    revised["weight_end"] = derived
    return revised


def _autostamp_prep_dates(prep_updates: dict[str, Any], preparation: Preparation) -> dict[str, Any]:
    """Stamp `prep_start` / `prep_end` with today's date when the
    corresponding weight has just been entered but the timestamp is empty.
    """
    revised = dict(prep_updates)
    today_dt = datetime.combine(date.today(), datetime.min.time())
    effective_start = revised.get("prep_start", preparation.prep_start)
    effective_end = revised.get("weight_end", preparation.weight_end)
    effective_prep_end = revised.get("prep_end", preparation.prep_end)
    effective_weight_start = revised.get("weight_start", preparation.weight_start)

    if effective_weight_start is not None and effective_start is None:
        revised.setdefault("prep_start", today_dt)
    if effective_end is not None and effective_prep_end is None:
        revised.setdefault("prep_end", today_dt)
    return revised


def _validate_prep_date_ordering(
    prep_updates: dict[str, Any], preparation: Preparation
) -> dict[str, str]:
    """`prep_end` must be on or after `prep_start`."""
    start = prep_updates.get("prep_start", preparation.prep_start)
    end = prep_updates.get("prep_end", preparation.prep_end)
    if start is not None and end is not None and end < start:
        return {"bench__prep_end": "Prep End must be on or after Prep Start."}
    return {}


def _calculate_yield(weight_start: Any, weight_end: Any) -> str | None:
    """Display string for the bench page's yield indicator. Returns None
    when either weight is missing or weight_start is zero."""
    if weight_start is None or weight_end is None:
        return None
    try:
        start = Decimal(str(weight_start))
        end = Decimal(str(weight_end))
    except (InvalidOperation, ValueError):
        return None
    if start == 0:
        return None
    yield_percent = (end / start) * Decimal("100")
    rounded = yield_percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(rounded, "f")


# ---- The bench class ------------------------------------------------------


class PreparationBench:
    """Workflow module for the Preparation bench page.

    Both methods leave commit responsibility to themselves: `save()`
    commits on success. (Cross-bench composition isn't a use case here, so
    we don't take the deeper module's flush-without-commit shape.)
    """

    def __init__(self, service: "SamsService") -> None:
        self.service = service
        self.repo = service.repo
        self.session = service.session

    # ---- Page-view side ----

    def page_view(
        self,
        *,
        show_on_hold: bool,
        sample_nr_raw: str,
        prep_nr_raw: str,
        form_values: dict[str, str] | None = None,
        field_errors: dict[str, str] | None = None,
        error: str | None = None,
        saved: bool = False,
        notice: str | None = None,
    ) -> dict[str, object]:
        """Build the template context for `lab_queue.html` (without `request`).

        Default cursor: when `sample_nr_raw` is empty, fall through to the
        first row of the planned-queue table the dashboard returns.
        """
        from sams_web.routers.pages_shared import parse_positive_int

        rows = self.service.get_dashboard(show_on_hold=show_on_hold)["tables"].get("planned", [])

        form_values = form_values or {}
        field_errors = field_errors or {}

        if not sample_nr_raw and rows:
            first = rows[0]
            if first.get("sample_nr") is not None:
                sample_nr_raw = str(first["sample_nr"])
            if first.get("prep_nr") is not None:
                prep_nr_raw = str(first["prep_nr"])

        sample_nr = parse_positive_int(sample_nr_raw) if sample_nr_raw else None
        prep_nr = parse_positive_int(prep_nr_raw) if prep_nr_raw else None

        bench_entry = None
        if sample_nr is not None:
            bench_entry = self._load_bench_entry(sample_nr, prep_nr)
            if bench_entry is None and error is None:
                error = "Sample or preparation was not found for bench entry."
            elif bench_entry is not None:
                prep_nr_raw = str(bench_entry["preparation"].prep_nr)

        return {
            "title": "Preparation Workflow",
            "description": "Preparation worklist for samples that are ready for pre-treatment planning and execution.",
            "table_key": "planned",
            "table_title": "Planned",
            "rows": rows,
            "show_on_hold": show_on_hold,
            "show_on_hold_enabled": True,
            "bench_entry_enabled": True,
            "bench_entry": bench_entry,
            "bench_sample_nr_query": sample_nr_raw,
            "bench_prep_nr_query": prep_nr_raw,
            "bench_form_values": form_values,
            "bench_field_errors": field_errors,
            "bench_error": error,
            "bench_saved": saved,
            "bench_notice": notice,
            "bench_method_options": self.service.list_preparation_methods(),
        }

    # ---- Save side ----

    def save(
        self,
        *,
        form_data: dict[str, str],
        sample_nr: int,
        prep_nr: int,
        action: str,
        show_on_hold: bool,
    ) -> BenchSaveOutcome:
        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return BenchSaveOutcome(success=False, save_error="Preparation not found.")
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return BenchSaveOutcome(success=False, save_error="Sample not found.")

        prep_updates, sample_updates, field_errors = self._decode_form(form_data)
        if field_errors:
            return BenchSaveOutcome(
                success=False,
                field_errors=field_errors,
                save_error="Please correct the highlighted fields and save again.",
            )

        prep_updates = _derive_weight_end(prep_updates, preparation)
        prep_updates = _autostamp_prep_dates(prep_updates, preparation)
        date_errors = _validate_prep_date_ordering(prep_updates, preparation)
        if date_errors:
            return BenchSaveOutcome(
                success=False,
                field_errors=date_errors,
                save_error="Please correct the highlighted fields and save again.",
            )

        for key, value in prep_updates.items():
            setattr(preparation, key, value)
        for key, value in sample_updates.items():
            setattr(sample, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        next_cursor: tuple[int, ...] | None = None
        if action == "save_next":
            rows = self.repo.list_planned_queue_rows(show_on_hold=show_on_hold)
            queue = queue_tuples(rows, "sample_nr", "prep_nr")
            next_cursor = next_queue_entry(queue, (sample_nr, prep_nr))

        return BenchSaveOutcome(success=True, next_cursor=next_cursor)

    # ---- Internal helpers ----

    def _load_bench_entry(self, sample_nr: int, prep_nr: int | None) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None
        preparations = sorted(
            self.repo.list_preparations_by_sample(sample_nr), key=lambda p: p.prep_nr
        )
        if not preparations:
            return None
        selected = select_preparation(preparations, prep_nr, open_attr_name="prep_end")
        if selected is None:
            return None
        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_submitter(project.user_nr) if project and project.user_nr else None
        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparation": selected,
            "preparations": preparations,
            "yield_percent": _calculate_yield(selected.weight_start, selected.weight_end),
            "sample_archived": bool((sample.s_storage_loc or "").strip()),
        }

    def _decode_form(
        self, form_data: dict[str, str]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
        prep_columns = model_columns(Preparation)
        sample_columns = model_columns(Sample)
        allowed_methods = {
            value for value in self.repo.get_methods() if value and value.strip()
        }
        prep_updates: dict[str, Any] = {}
        sample_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        for field_name, raw_value in form_data.items():
            if not field_name.startswith(_FORM_PREFIX):
                continue
            field_key = field_name.removeprefix(_FORM_PREFIX)
            if field_key in _RESERVED_FORM_KEYS:
                continue

            if field_key in _SAMPLE_FIELDS:
                column = sample_columns.get(field_key)
                if column is None:
                    continue
                coerced, error = coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                sample_updates[field_key] = coerced
                continue

            if field_key not in _PREP_FIELDS:
                continue
            column = prep_columns.get(field_key)
            if column is None:
                continue
            coerced, error = coerce_column_value(column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue
            if field_key in _METHOD_FIELDS:
                if coerced is not None and str(coerced) not in allowed_methods:
                    field_errors[field_name] = "Value must be selected from the dropdown list."
                    continue
            prep_updates[field_key] = coerced

        return prep_updates, sample_updates, field_errors

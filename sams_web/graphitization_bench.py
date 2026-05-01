"""Graphitization bench: workflow module owning the graph bench page,
the per-target save, and the bulk graph-batch assignment that lives on
the same page.

Replaces logic that was spread across `services.py`
(`get_graphitization_bench_entry`, `get_next_graphitization_bench_entry`,
`update_graphitization_bench_entry`, `save_graph_batch_assignments`) and
the `_build_lab_graphitization_page_context` builder in
`routers/pages_search_lab_import.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from sams_web.bench_helpers import (
    BenchSaveOutcome,
    next_queue_entry,
    queue_tuples,
    select_preparation,
    select_target,
)
from sams_web.detail_update import coerce_column_value, model_columns
from sams_web.models import Preparation, Sample, Target

if TYPE_CHECKING:
    from sams_web.services import SamsService


_FORM_PREFIX = "graphbench__"
_RESERVED_FORM_KEYS = frozenset({"sample_nr", "prep_nr", "target_nr", "action"})

_SAMPLE_FIELDS: frozenset[str] = frozenset({"prep_storage_loc", "c_n_isotop_a_moved"})
_PREP_FIELDS: frozenset[str] = frozenset({"p_no_leftover"})
_TARGET_FIELDS: frozenset[str] = frozenset({"weight_combustion", "stop", "target_comment"})


@dataclass
class BatchAssignOutcome:
    """Result of `assign_graph_batch`."""

    success: bool
    error: str | None = None


# ---- The bench class ------------------------------------------------------


class GraphitizationBench:
    """Workflow module for the Graphitization bench page.

    Owns three operations:
    - `page_view(...)` builds the lab_queue.html context (without `request`).
    - `save(...)` applies a per-target bench submit and optionally finds
      the next queue entry.
    - `assign_graph_batch(...)` bulk-assigns N targets to a graph batch
      name (the "save batch" button on the page).
    """

    def __init__(self, service: "SamsService") -> None:
        self.service = service
        self.repo = service.repo
        self.session = service.session

    # ---- Page-view side ----

    def page_view(
        self,
        *,
        sample_nr_raw: str,
        prep_nr_raw: str,
        target_nr_raw: str,
        form_values: dict[str, str] | None = None,
        field_errors: dict[str, str] | None = None,
        error: str | None = None,
        saved: bool = False,
        notice: str | None = None,
        batch_notice: str | None = None,
        batch_error: str | None = None,
    ) -> dict[str, object]:
        from sams_web.routers.pages_shared import parse_positive_int

        rows = self.service.get_dashboard(show_on_hold=False)["tables"].get(
            "waiting_for_graph", []
        )

        form_values = form_values or {}
        field_errors = field_errors or {}

        if not sample_nr_raw and rows:
            first = rows[0]
            if first.get("sample_nr") is not None:
                sample_nr_raw = str(first["sample_nr"])
            if first.get("prep_nr") is not None:
                prep_nr_raw = str(first["prep_nr"])
            if first.get("target_nr") is not None:
                target_nr_raw = str(first["target_nr"])

        sample_nr = parse_positive_int(sample_nr_raw) if sample_nr_raw else None
        prep_nr = parse_positive_int(prep_nr_raw) if prep_nr_raw else None
        target_nr = parse_positive_int(target_nr_raw) if target_nr_raw else None

        bench_entry = None
        if sample_nr is not None:
            bench_entry = self._load_bench_entry(sample_nr, prep_nr, target_nr)
            if bench_entry is None and error is None:
                error = "Sample / preparation / target was not found for graphitization bench entry."
            elif bench_entry is not None:
                prep_nr_raw = str(bench_entry["preparation"].prep_nr)
                target_nr_raw = str(bench_entry["target"].target_nr)

        return {
            "title": "Graphitization Workflow",
            "description": "Graphitization worklist for samples waiting to enter target production.",
            "table_key": "waiting_for_graph",
            "table_title": "Waiting For Graph",
            "rows": rows,
            "show_on_hold": False,
            "show_on_hold_enabled": False,
            "graph_bench_entry_enabled": True,
            "graph_bench_entry": bench_entry,
            "graph_sample_nr_query": sample_nr_raw,
            "graph_prep_nr_query": prep_nr_raw,
            "graph_target_nr_query": target_nr_raw,
            "graph_form_values": form_values,
            "graph_field_errors": field_errors,
            "graph_error": error,
            "graph_saved": saved,
            "graph_notice": notice,
            "graph_batch_notice": batch_notice,
            "graph_batch_error": batch_error,
            "graph_batch_system_options": self.service.get_graphitization_systems(),
        }

    # ---- Save side (per-target) ----

    def save(
        self,
        *,
        form_data: dict[str, str],
        sample_nr: int,
        prep_nr: int,
        target_nr: int,
        action: str,
    ) -> BenchSaveOutcome:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return BenchSaveOutcome(success=False, save_error="Sample not found.")
        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return BenchSaveOutcome(success=False, save_error="Preparation not found.")
        target = self.repo.get_target(sample_nr, prep_nr, target_nr)
        if target is None:
            return BenchSaveOutcome(success=False, save_error="Target not found.")

        sample_updates, prep_updates, target_updates, field_errors = self._decode_form(form_data)
        if field_errors:
            return BenchSaveOutcome(
                success=False,
                field_errors=field_errors,
                save_error="Please correct the highlighted fields and save again.",
            )

        for key, value in sample_updates.items():
            setattr(sample, key, value)
        for key, value in prep_updates.items():
            setattr(preparation, key, value)
        for key, value in target_updates.items():
            setattr(target, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        next_cursor: tuple[int, ...] | None = None
        if action == "save_next":
            rows = self.repo.list_waiting_for_graph_queue_rows()
            queue = queue_tuples(rows, "sample_nr", "prep_nr", "target_nr")
            next_cursor = next_queue_entry(queue, (sample_nr, prep_nr, target_nr))

        return BenchSaveOutcome(success=True, next_cursor=next_cursor)

    # ---- Bulk graph-batch assignment ----

    def assign_graph_batch(
        self,
        *,
        batch_name: str,
        target_keys: list[tuple[int, int, int]],
    ) -> BatchAssignOutcome:
        normalized_name = (batch_name or "").strip()
        if normalized_name == "":
            return BatchAssignOutcome(False, "Batch name is required.")
        if not normalized_name.lower().startswith("graph_"):
            return BatchAssignOutcome(False, "Batch name must start with 'graph_'.")
        if not target_keys:
            return BatchAssignOutcome(False, "No targets were provided for batch assignment.")

        unique_keys = list(dict.fromkeys(target_keys))
        targets = self.repo.get_targets_for_batch_assignment(unique_keys)
        if len(targets) != len(unique_keys):
            return BatchAssignOutcome(False, "One or more selected targets could not be found.")

        by_key = {(t.sample_nr, t.prep_nr, t.target_nr): t for t in targets}
        for key in unique_keys:
            target = by_key[key]
            existing_batch = (target.graph_batch or "").strip()
            if existing_batch and existing_batch != normalized_name:
                return BatchAssignOutcome(
                    False,
                    f"Target {key[0]}/{key[1]}/{key[2]} is already assigned to graph batch '{existing_batch}'.",
                )

        for key in unique_keys:
            by_key[key].graph_batch = normalized_name

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return BatchAssignOutcome(True)

    # ---- Internal helpers ----

    def _load_bench_entry(
        self, sample_nr: int, prep_nr: int | None, target_nr: int | None
    ) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None
        preparations = sorted(
            self.repo.list_preparations_by_sample(sample_nr), key=lambda p: p.prep_nr
        )
        if not preparations:
            return None
        selected_prep = select_preparation(preparations, prep_nr)
        if selected_prep is None:
            return None
        prep_targets = self.repo.list_targets_by_sample(
            sample_nr, prep_nr=selected_prep.prep_nr
        )
        if not prep_targets:
            return None
        selected_target = select_target(prep_targets, target_nr)
        if selected_target is None:
            return None
        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_submitter(project.user_nr) if project and project.user_nr else None
        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparation": selected_prep,
            "target": selected_target,
            "preparations": preparations,
            "targets": prep_targets,
            "prep_archived": bool((sample.prep_storage_loc or "").strip()),
        }

    def _decode_form(
        self, form_data: dict[str, str]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, str]]:
        sample_columns = model_columns(Sample)
        prep_columns = model_columns(Preparation)
        target_columns = model_columns(Target)
        sample_updates: dict[str, Any] = {}
        prep_updates: dict[str, Any] = {}
        target_updates: dict[str, Any] = {}
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

            if field_key in _PREP_FIELDS:
                column = prep_columns.get(field_key)
                if column is None:
                    continue
                coerced, error = coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                prep_updates[field_key] = coerced
                continue

            if field_key in _TARGET_FIELDS:
                column = target_columns.get(field_key)
                if column is None:
                    continue
                coerced, error = coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                target_updates[field_key] = coerced

        return sample_updates, prep_updates, target_updates, field_errors

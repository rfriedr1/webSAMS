"""Service layer for SAMS business workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any

from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.orm import Session
from sqlalchemy.sql.sqltypes import Date as SQLDate
from sqlalchemy.sql.sqltypes import DateTime as SQLDateTime
from sqlalchemy.sql.sqltypes import Float as SQLFloat
from sqlalchemy.sql.sqltypes import Integer as SQLInteger

from sams_web.bench_helpers import next_queue_entry, queue_tuples, select_preparation, select_target
from sams_web.models import Preparation, Project, Sample, Target, User
from sams_web.repositories import SamsRepository
from sams_web.setup_sections import (
    SETUP_SECTION_GRAPHITIZATION_SYSTEMS,
    SETUP_SECTION_MAP,
    SETUP_SECTION_STANDARD_THRESHOLDS,
    SETUP_SECTIONS,
)
from sams_web.setup_store import SetupStore
from sams_web.thresholds import THRESHOLD_FIELDS, ThresholdRule, ThresholdStore


@dataclass
class TextSanitizer:
    """Ported from `_dm.pas` string cleanup helpers."""

    @staticmethod
    def replace_bad_characters(value: str) -> str:
        return (
            value.replace(";", ",")
            .replace("&", "_")
            .replace("%", "_")
            .replace("$", "_")
            .replace("?", "")
            .replace('"', "")
        )

    @staticmethod
    def replace_umlaute(value: str) -> str:
        return (
            value.replace("ä", "ae")
            .replace("ü", "ue")
            .replace("ö", "oe")
            .replace("ß", "ss")
            .replace("Ä", "Ae")
            .replace("Ü", "Ue")
            .replace("Ö", "Oe")
        )


def _model_columns(model: type[Any]) -> dict[str, Any]:
    mapper = sa_inspect(model).mapper
    return {attr.key: attr.columns[0] for attr in mapper.column_attrs}


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped != "" else None


def _coerce_column_value(column: Any, raw_value: str | None) -> tuple[Any, str | None]:
    normalized = _normalize_text(raw_value)
    if normalized is None:
        return None, None

    try:
        if isinstance(column.type, SQLInteger):
            return int(normalized), None
        if isinstance(column.type, SQLFloat):
            return float(normalized), None
        if isinstance(column.type, SQLDate):
            return date.fromisoformat(normalized), None
        if isinstance(column.type, SQLDateTime):
            return datetime.fromisoformat(normalized), None
    except ValueError:
        return None, "Invalid value format."

    return normalized, None


def _pick_closed_project_status(statuses: list[str]) -> str | None:
    cleaned = [status.strip() for status in statuses if status and status.strip()]
    if not cleaned:
        return None

    lowered = {status.lower(): status for status in cleaned}
    exact_closed = lowered.get("closed")
    if exact_closed is not None:
        return exact_closed

    for status in cleaned:
        if "closed" in status.lower():
            return status

    for candidate in ("complete", "completed", "done", "finished", "report-ready", "reported"):
        matched = lowered.get(candidate)
        if matched is not None:
            return matched

    return None


GRAPHITIZATION_SYSTEM_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
DEFAULT_GRAPHITIZATION_SYSTEMS = [
    "mag",
    "age.1",
    "age.2",
    "age64.1",
    "age64.2",
    "autosampler",
]


class SamsService:
    """Application service implementing migrated Delphi data flows."""

    def __init__(
        self,
        session: Session,
        threshold_store: ThresholdStore,
        setup_store: SetupStore,
    ) -> None:
        self.session = session
        self.repo = SamsRepository(session)
        self.threshold_store = threshold_store
        self.setup_store = setup_store

    def get_dashboard(self, show_on_hold: bool = False) -> dict[str, Any]:
        standards = self.repo.get_standard_counts()
        thresholds = self.threshold_store.load()
        return {
            "counts": self.repo.get_dashboard_counts(show_on_hold=show_on_hold),
            "tables": self.repo.get_dashboard_tables(show_on_hold=show_on_hold),
            "standards": standards,
            "standard_statuses": self._standard_statuses(standards, thresholds),
            "standard_thresholds": ThresholdStore.as_payload(thresholds),
        }

    def get_projects_in_progress(
        self,
        *,
        days_window: int = 300,
        include_internal: bool = False,
    ) -> list[dict[str, Any]]:
        return self.repo.get_projects_in_progress(
            days_window=days_window,
            include_internal=include_internal,
        )

    def list_users(self, query: str | None = None, limit: int | None = None):
        return self.repo.list_users(query=query, limit=limit)

    def get_user_details(self, user_nr: int):
        user = self.repo.get_user(user_nr)
        if user is None:
            return None
        previous_user_nr, next_user_nr = self.repo.get_adjacent_user_nrs(user_nr)
        user_count, max_user_nr = self.repo.get_user_stats()
        return {
            "user": user,
            "projects": self.repo.list_projects_by_user(user_nr),
            "previous_user_nr": previous_user_nr,
            "next_user_nr": next_user_nr,
            "user_count": user_count,
            "max_user_nr": max_user_nr,
        }

    def update_user_detail(
        self,
        user_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        user = self.repo.get_user(user_nr)
        if user is None:
            return False, {}, "User not found."

        user_columns = _model_columns(User)
        user_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("user__"):
                continue
            field_key = field_name.removeprefix("user__")
            if field_key == "user_nr":
                continue

            user_column = user_columns.get(field_key)
            if user_column is None:
                continue
            coerced_value, error = _coerce_column_value(user_column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue
            user_updates[field_key] = coerced_value

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        for key, value in user_updates.items():
            setattr(user, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, {}, None

    def get_user_projects(self, user_nr: int):
        data = self.get_user_details(user_nr)
        if data is None:
            return None
        return data

    def list_projects(self, limit: int | None = None):
        return self.repo.list_projects(limit=limit)

    def get_project_details(self, project_nr: int):
        project = self.repo.get_project(project_nr)
        if project is None:
            return None
        user = self.repo.get_user(project.user_nr) if project.user_nr else None
        previous_project_nr, next_project_nr = self.repo.get_adjacent_project_nrs(project_nr)
        project_count, max_project_nr = self.repo.get_project_stats()
        return {
            "project": project,
            "user": user,
            "samples": self.repo.list_samples_by_project(project_nr),
            "previous_project_nr": previous_project_nr,
            "next_project_nr": next_project_nr,
            "project_count": project_count,
            "max_project_nr": max_project_nr,
        }

    def get_project_edit_select_options(self) -> dict[str, list[str]]:
        return {
            "project__status": self.repo.get_project_statuses(),
            "project__project_type": self.repo.get_project_types(),
            "project__research": self.repo.get_research_values(),
            "project__report_type": self.repo.get_report_types(),
        }

    def update_project_detail(
        self,
        project_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        project = self.repo.get_project(project_nr)
        if project is None:
            return False, {}, "Project not found."

        project_columns = _model_columns(Project)
        project_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        allowed_values_by_field = {
            "status": {value for value in self.repo.get_project_statuses() if value and value.strip()},
            "project_type": {value for value in self.repo.get_project_types() if value and value.strip()},
            "research": {value for value in self.repo.get_research_values() if value and value.strip()},
            "report_type": {value for value in self.repo.get_report_types() if value and value.strip()},
        }

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("project__"):
                continue
            field_key = field_name.removeprefix("project__")
            if field_key in {"project_nr", "user_nr"}:
                continue

            project_column = project_columns.get(field_key)
            if project_column is None:
                continue
            coerced_value, error = _coerce_column_value(project_column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue

            allowed_values = allowed_values_by_field.get(field_key)
            if allowed_values is not None and coerced_value is not None and str(coerced_value) not in allowed_values:
                field_errors[field_name] = "Value must be selected from the dropdown list."
                continue

            project_updates[field_key] = coerced_value

        effective_in_date = project_updates.get("in_date", project.in_date)
        effective_desired_date = project_updates.get("desired_date", project.desired_date)
        effective_out_date = project_updates.get("out_date", project.out_date)

        if (
            effective_in_date is not None
            and effective_desired_date is not None
            and effective_desired_date < effective_in_date
        ):
            field_errors["project__desired_date"] = "Desired Date must be on or after In Date."

        if effective_out_date is not None and effective_in_date is not None and effective_out_date < effective_in_date:
            field_errors["project__out_date"] = "Out Date must be on or after In Date."

        project_out_date_changed = "out_date" in project_updates and project_updates.get("out_date") != project.out_date
        if project_out_date_changed and effective_out_date is not None:
            allowed_statuses = self.repo.get_project_statuses()
            auto_closed_status = _pick_closed_project_status(allowed_statuses)
            if auto_closed_status is None:
                field_errors.setdefault(
                    "project__out_date",
                    "Out Date requires a closing status configured in projectstatus_t.",
                )
            else:
                project_updates["status"] = auto_closed_status

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        for key, value in project_updates.items():
            setattr(project, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, {}, None

    def get_project_samples(self, project_nr: int):
        data = self.get_project_details(project_nr)
        if data is None:
            return None
        return {
            "project": data["project"],
            "samples": data["samples"],
        }

    def get_sample_details(self, sample_nr: int):
        return self.repo.get_sample_details(sample_nr)

    def sample_exists(self, sample_nr: int) -> bool:
        return self.repo.get_sample(sample_nr) is not None

    def resolve_samples_landing_sample_nr(self, preferred_sample_nr: int | None = None) -> int | None:
        if preferred_sample_nr is not None and preferred_sample_nr > 0 and self.sample_exists(preferred_sample_nr):
            return preferred_sample_nr
        _, max_sample_nr = self.repo.get_sample_stats()
        if max_sample_nr > 0:
            return max_sample_nr
        return None

    def preparation_exists(self, sample_nr: int, prep_nr: int) -> bool:
        return self.repo.get_preparation(sample_nr, prep_nr) is not None

    def get_preparation_bench_entry(
        self,
        sample_nr: int,
        prep_nr: int | None = None,
    ) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None

        preparations = sorted(self.repo.list_preparations_by_sample(sample_nr), key=lambda p: p.prep_nr)
        if not preparations:
            return None

        selected_preparation = select_preparation(preparations, prep_nr, open_attr_name="prep_end")
        if selected_preparation is None:
            return None

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_user(project.user_nr) if project and project.user_nr else None

        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparation": selected_preparation,
            "preparations": preparations,
            "yield_percent": self._calculate_bench_yield(
                selected_preparation.weight_start,
                selected_preparation.weight_end,
            ),
            "sample_archived": bool((sample.s_storage_loc or "").strip()),
        }

    def get_next_planned_bench_entry(
        self,
        sample_nr: int,
        prep_nr: int,
        *,
        show_on_hold: bool = False,
    ) -> tuple[int, int] | None:
        rows = self.repo.list_planned_queue_rows(show_on_hold=show_on_hold)
        queue = queue_tuples(rows, "sample_nr", "prep_nr")
        return next_queue_entry(queue, (sample_nr, prep_nr))

    def get_graphitization_bench_entry(
        self,
        sample_nr: int,
        prep_nr: int | None = None,
        target_nr: int | None = None,
    ) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None

        preparations = sorted(self.repo.list_preparations_by_sample(sample_nr), key=lambda p: p.prep_nr)
        if not preparations:
            return None

        selected_preparation = select_preparation(preparations, prep_nr)
        if selected_preparation is None:
            return None

        prep_targets = self.repo.list_targets_by_sample(sample_nr, prep_nr=selected_preparation.prep_nr)
        if not prep_targets:
            return None

        selected_target = select_target(prep_targets, target_nr)
        if selected_target is None:
            return None

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_user(project.user_nr) if project and project.user_nr else None

        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparation": selected_preparation,
            "target": selected_target,
            "preparations": preparations,
            "targets": prep_targets,
            "prep_archived": bool((sample.prep_storage_loc or "").strip()),
        }

    def get_next_graphitization_bench_entry(
        self,
        sample_nr: int,
        prep_nr: int,
        target_nr: int,
    ) -> tuple[int, int, int] | None:
        rows = self.repo.list_waiting_for_graph_queue_rows()
        queue = queue_tuples(rows, "sample_nr", "prep_nr", "target_nr")
        return next_queue_entry(queue, (sample_nr, prep_nr, target_nr))

    def update_graphitization_bench_entry(
        self,
        sample_nr: int,
        prep_nr: int,
        target_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return False, {}, "Sample not found."
        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return False, {}, "Preparation not found."
        target = self.repo.get_target(sample_nr, prep_nr, target_nr)
        if target is None:
            return False, {}, "Target not found."

        sample_columns = _model_columns(Sample)
        prep_columns = _model_columns(Preparation)
        target_columns = _model_columns(Target)
        sample_updates: dict[str, Any] = {}
        prep_updates: dict[str, Any] = {}
        target_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        sample_field_keys = {"prep_storage_loc", "c_n_isotop_a_moved"}
        prep_field_keys = {"p_no_leftover"}
        target_field_keys = {"weight_combustion", "stop", "target_comment"}

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("graphbench__"):
                continue
            field_key = field_name.removeprefix("graphbench__")
            if field_key in {"sample_nr", "prep_nr", "target_nr", "action"}:
                continue

            if field_key in sample_field_keys:
                column = sample_columns.get(field_key)
                if column is None:
                    continue
                coerced_value, error = _coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                sample_updates[field_key] = coerced_value
                continue

            if field_key in prep_field_keys:
                column = prep_columns.get(field_key)
                if column is None:
                    continue
                coerced_value, error = _coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                prep_updates[field_key] = coerced_value
                continue

            if field_key in target_field_keys:
                column = target_columns.get(field_key)
                if column is None:
                    continue
                coerced_value, error = _coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                target_updates[field_key] = coerced_value

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

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

        return True, {}, None

    def save_graph_batch_assignments(
        self,
        *,
        batch_name: str,
        target_keys: list[tuple[int, int, int]],
    ) -> tuple[bool, str | None]:
        normalized_name = (batch_name or "").strip()
        if normalized_name == "":
            return False, "Batch name is required."
        if not normalized_name.lower().startswith("graph_"):
            return False, "Batch name must start with 'graph_'."
        if not target_keys:
            return False, "No targets were provided for batch assignment."

        unique_keys = list(dict.fromkeys(target_keys))
        targets = self.repo.get_targets_for_batch_assignment(unique_keys)
        if len(targets) != len(unique_keys):
            return False, "One or more selected targets could not be found."

        by_key = {(t.sample_nr, t.prep_nr, t.target_nr): t for t in targets}
        for key in unique_keys:
            target = by_key[key]
            existing_batch = (target.graph_batch or "").strip()
            if existing_batch and existing_batch != normalized_name:
                return False, f"Target {key[0]}/{key[1]}/{key[2]} is already assigned to graph batch '{existing_batch}'."

        for key in unique_keys:
            by_key[key].graph_batch = normalized_name

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, None

    def update_preparation_bench_entry(
        self,
        sample_nr: int,
        prep_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return False, {}, "Preparation not found."
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return False, {}, "Sample not found."

        prep_columns = _model_columns(Preparation)
        sample_columns = _model_columns(Sample)
        prep_updates: dict[str, Any] = {}
        sample_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        prep_field_keys = {
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
        }
        sample_field_keys = {"s_no_leftover", "s_storage_loc"}
        allowed_methods = {value for value in self.repo.get_methods() if value and value.strip()}

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("bench__"):
                continue
            field_key = field_name.removeprefix("bench__")
            if field_key in {"sample_nr", "prep_nr", "action", "show_on_hold"}:
                continue

            if field_key in sample_field_keys:
                column = sample_columns.get(field_key)
                if column is None:
                    continue
                coerced_value, error = _coerce_column_value(column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                sample_updates[field_key] = coerced_value
                continue

            if field_key not in prep_field_keys:
                continue
            column = prep_columns.get(field_key)
            if column is None:
                continue
            coerced_value, error = _coerce_column_value(column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue
            if field_key in {"step1_method", "step2_method", "step3_method", "step4_method", "step5_method"}:
                if coerced_value is not None and str(coerced_value) not in allowed_methods:
                    field_errors[field_name] = "Value must be selected from the dropdown list."
                    continue
            prep_updates[field_key] = coerced_value

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        effective_weight_start = prep_updates.get("weight_start", preparation.weight_start)
        effective_weight_medium = prep_updates.get("weight_medium", preparation.weight_medium)
        effective_weight_medium_2 = prep_updates.get("weight_medium_2", preparation.weight_medium_2)
        effective_weight_end = prep_updates.get("weight_end", preparation.weight_end)
        effective_prep_start = prep_updates.get("prep_start", preparation.prep_start)
        effective_prep_end = prep_updates.get("prep_end", preparation.prep_end)

        # If weight_end is not provided yet, prefill from the two intermediate weights.
        if ("weight_end" not in prep_updates or effective_weight_end is None) and effective_weight_medium is not None and effective_weight_medium_2 is not None:
            try:
                computed_weight_end = float(Decimal(str(effective_weight_medium)) - Decimal(str(effective_weight_medium_2)))
            except (InvalidOperation, ValueError):
                computed_weight_end = None
            if computed_weight_end is not None:
                prep_updates["weight_end"] = computed_weight_end
                effective_weight_end = computed_weight_end

        now_date = date.today()
        if effective_weight_start is not None and effective_prep_start is None:
            prep_updates.setdefault("prep_start", datetime.combine(now_date, datetime.min.time()))
            effective_prep_start = prep_updates.get("prep_start")
        if effective_weight_end is not None and effective_prep_end is None:
            prep_updates.setdefault("prep_end", datetime.combine(now_date, datetime.min.time()))
            effective_prep_end = prep_updates.get("prep_end")

        if (
            effective_prep_start is not None
            and effective_prep_end is not None
            and effective_prep_end < effective_prep_start
        ):
            field_errors["bench__prep_end"] = "Prep End must be on or after Prep Start."

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        for key, value in prep_updates.items():
            setattr(preparation, key, value)
        for key, value in sample_updates.items():
            setattr(sample, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, {}, None

    def list_preparation_methods(self) -> list[str]:
        return self.repo.get_methods()

    def get_graphitization_systems(self) -> list[str]:
        raw = self.setup_store.get_section(
            SETUP_SECTION_GRAPHITIZATION_SYSTEMS,
            default=list(DEFAULT_GRAPHITIZATION_SYSTEMS),
        )
        if not isinstance(raw, list):
            return list(DEFAULT_GRAPHITIZATION_SYSTEMS)
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if not value:
                continue
            if not GRAPHITIZATION_SYSTEM_VALUE_PATTERN.fullmatch(value):
                continue
            if value in seen:
                continue
            cleaned.append(value)
            seen.add(value)
        return cleaned or list(DEFAULT_GRAPHITIZATION_SYSTEMS)

    def get_preparation_edit_select_options(self) -> dict[str, list[str]]:
        methods = self.repo.get_methods()
        return {
            "preparation__step1_method": methods,
            "preparation__step2_method": methods,
            "preparation__step3_method": methods,
            "preparation__step4_method": methods,
            "preparation__step5_method": methods,
        }

    def update_preparation_detail(
        self,
        sample_nr: int,
        prep_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return False, {}, "Preparation not found."

        prep_columns = _model_columns(Preparation)
        prep_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}
        allowed_methods = {value for value in self.repo.get_methods() if value and value.strip()}

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("preparation__"):
                continue
            field_key = field_name.removeprefix("preparation__")
            if field_key in {"sample_nr", "prep_nr", "yield_percent"}:
                continue

            prep_column = prep_columns.get(field_key)
            if prep_column is None:
                continue
            coerced_value, error = _coerce_column_value(prep_column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue

            if field_key in {"step1_method", "step2_method", "step3_method", "step4_method", "step5_method"}:
                if coerced_value is not None and str(coerced_value) not in allowed_methods:
                    field_errors[field_name] = "Value must be selected from the dropdown list."
                    continue

            prep_updates[field_key] = coerced_value

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        for key, value in prep_updates.items():
            setattr(preparation, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, {}, None

    @staticmethod
    def _calculate_bench_yield(weight_start: Any, weight_end: Any) -> str | None:
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

    def update_target_detail(
        self,
        sample_nr: int,
        prep_nr: int,
        target_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        target = self.repo.get_target(sample_nr, prep_nr, target_nr)
        if target is None:
            return False, {}, "Target not found."

        target_columns = _model_columns(Target)
        target_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("target__"):
                continue
            field_key = field_name.removeprefix("target__")
            if field_key in {"sample_nr", "prep_nr", "target_nr", "target_id"}:
                continue

            target_column = target_columns.get(field_key)
            if target_column is None:
                continue

            coerced_value, error = _coerce_column_value(target_column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue

            target_updates[field_key] = coerced_value

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        for key, value in target_updates.items():
            setattr(target, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, {}, None

    def target_exists(self, sample_nr: int, prep_nr: int, target_nr: int) -> bool:
        return self.repo.get_target(sample_nr, prep_nr, target_nr) is not None

    def list_targets_by_magazine(self, magazine_query: str) -> list[dict[str, Any]]:
        return self.repo.list_targets_by_magazine(magazine_query)

    def list_magazines(self) -> list[str]:
        return self.repo.list_magazines()

    def resolve_existing_magazine(self, magazine_query: str) -> str | None:
        return self.repo.resolve_existing_magazine(magazine_query)

    def project_exists(self, project_nr: int) -> bool:
        return self.repo.get_project(project_nr) is not None

    def user_exists(self, user_nr: int) -> bool:
        return self.repo.get_user(user_nr) is not None

    def get_sample_overview(
        self,
        sample_nr: int,
    ) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_user(project.user_nr) if project and project.user_nr else None
        preparations = self.repo.list_preparations_by_sample(sample_nr)
        targets_by_prep = self.repo.count_targets_by_prep(sample_nr)
        targets = self.repo.list_targets_by_sample(sample_nr, prep_nr=None)
        sample_targets_total = len(targets)
        previous_sample_nr, next_sample_nr = self.repo.get_adjacent_sample_nrs(sample_nr)
        sample_count, max_sample_nr = self.repo.get_sample_stats()

        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparations": preparations,
            "targets_by_prep": targets_by_prep,
            "targets": targets,
            "sample_targets_total": sample_targets_total,
            "previous_sample_nr": previous_sample_nr,
            "next_sample_nr": next_sample_nr,
            "sample_count": sample_count,
            "max_sample_nr": max_sample_nr,
        }

    def get_sample_edit_select_options(self) -> dict[str, list[str]]:
        lookups = self.get_lookups()
        return {
            "sample__type": lookups["sample_types"],
            "sample__material": lookups["materials"],
            "sample__fraction": lookups["fractions"],
        }

    def update_sample_detail(
        self,
        sample_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return False, {}, "Sample not found."

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        sample_columns = _model_columns(Sample)
        project_columns = _model_columns(Project)
        sample_updates: dict[str, Any] = {}
        project_updates: dict[str, Any] = {}
        field_errors: dict[str, str] = {}

        allowed_values_by_field = {
            "type": {value for value in self.repo.get_sample_types() if value and value.strip()},
            "material": {value for value in self.repo.get_materials() if value and value.strip()},
            "fraction": {value for value in self.repo.get_fractions() if value and value.strip()},
        }

        for field_name, raw_value in submitted_fields.items():
            if not field_name.startswith("sample__"):
                continue
            field_key = field_name.removeprefix("sample__")
            if field_key in {"sample_nr", "project_nr"}:
                continue

            if field_key.startswith("project_"):
                project_field = field_key.removeprefix("project_")
                if project is None:
                    field_errors[field_name] = "This sample has no linked project."
                    continue
                project_column = project_columns.get(project_field)
                if project_column is None:
                    continue
                coerced_value, error = _coerce_column_value(project_column, raw_value)
                if error is not None:
                    field_errors[field_name] = error
                    continue
                project_updates[project_field] = coerced_value
                continue

            sample_column = sample_columns.get(field_key)
            if sample_column is None:
                continue
            coerced_value, error = _coerce_column_value(sample_column, raw_value)
            if error is not None:
                field_errors[field_name] = error
                continue

            allowed_values = allowed_values_by_field.get(field_key)
            if allowed_values is not None and coerced_value is not None and str(coerced_value) not in allowed_values:
                field_errors[field_name] = "Value must be selected from the dropdown list."
                continue

            sample_updates[field_key] = coerced_value

        required_fields = {
            "sample__type": "Type is required.",
            "sample__material": "Material is required.",
            "sample__fraction": "Fraction is required.",
            "sample__project_in_date": "Project In Date is required.",
            "sample__project_desired_date": "Project Desired Date is required.",
        }

        if project is None:
            field_errors.setdefault("sample__project_in_date", "Project In Date is required.")
            field_errors.setdefault("sample__project_desired_date", "Project Desired Date is required.")

        for field_name, error_message in required_fields.items():
            if field_name in field_errors:
                continue
            field_key = field_name.removeprefix("sample__")
            if field_key.startswith("project_"):
                project_field = field_key.removeprefix("project_")
                current_value = project_updates.get(project_field, getattr(project, project_field, None) if project is not None else None)
            else:
                current_value = sample_updates.get(field_key, getattr(sample, field_key, None))
            if current_value is None or (isinstance(current_value, str) and current_value.strip() == ""):
                field_errors[field_name] = error_message

        effective_project_in_date = project_updates.get("in_date", getattr(project, "in_date", None))
        effective_project_desired_date = project_updates.get("desired_date", getattr(project, "desired_date", None))
        effective_project_out_date = project_updates.get("out_date", getattr(project, "out_date", None))

        if (
            effective_project_in_date is not None
            and effective_project_desired_date is not None
            and effective_project_desired_date < effective_project_in_date
        ):
            field_errors["sample__project_desired_date"] = "Project Desired Date must be on or after Project In Date."

        if (
            effective_project_out_date is not None
            and effective_project_in_date is not None
            and effective_project_out_date < effective_project_in_date
        ):
            field_errors["sample__project_out_date"] = "Project Out Date must be on or after Project In Date."

        previous_project_out_date = getattr(project, "out_date", None) if project is not None else None
        project_out_date_changed = (
            "out_date" in project_updates and project_updates.get("out_date") != previous_project_out_date
        )
        if project is not None and project_out_date_changed and effective_project_out_date is not None:
            allowed_statuses = self.repo.get_project_statuses()
            auto_closed_status = _pick_closed_project_status(allowed_statuses)
            if auto_closed_status is None:
                field_errors.setdefault(
                    "sample__project_out_date",
                    "Project Out Date requires a closing status configured in projectstatus_t.",
                )
            else:
                project_updates["status"] = auto_closed_status

        if field_errors:
            return False, field_errors, "Please correct the highlighted fields and save again."

        for key, value in sample_updates.items():
            setattr(sample, key, value)
        if project is not None:
            for key, value in project_updates.items():
                setattr(project, key, value)

        try:
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

        return True, {}, None

    def get_preparation_details(
        self,
        sample_nr: int,
        prep_nr: int,
    ) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None

        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return None

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_user(project.user_nr) if project and project.user_nr else None
        previous_prep_nr, next_prep_nr = self.repo.get_adjacent_prep_nrs(sample_nr, prep_nr)
        preparation_count, max_prep_nr = self.repo.get_preparation_stats(sample_nr)
        targets = self.repo.list_targets_by_sample(
            sample_nr,
            prep_nr=prep_nr,
        )
        targets_total = len(targets)

        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparation": preparation,
            "targets": targets,
            "targets_total": targets_total,
            "previous_prep_nr": previous_prep_nr,
            "next_prep_nr": next_prep_nr,
            "preparation_count": preparation_count,
            "max_prep_nr": max_prep_nr,
        }

    def get_target_details(self, sample_nr: int, prep_nr: int, target_nr: int) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None

        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            return None

        target = self.repo.get_target(sample_nr, prep_nr, target_nr)
        if target is None:
            return None

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_user(project.user_nr) if project and project.user_nr else None
        preparations = self.repo.list_preparations_by_sample(sample_nr)
        previous_target_nr, next_target_nr = self.repo.get_adjacent_target_nrs(sample_nr, prep_nr, target_nr)
        target_count, max_target_nr = self.repo.get_target_stats(sample_nr, prep_nr)

        return {
            "sample": sample,
            "project": project,
            "user": user,
            "preparation": preparation,
            "target": target,
            "preparations": preparations,
            "previous_target_nr": previous_target_nr,
            "next_target_nr": next_target_nr,
            "target_count": target_count,
            "max_target_nr": max_target_nr,
        }

    def search(self, context: str, phrase: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.repo.global_search(context=context, phrase=phrase, limit=limit)

    def create_user(self, payload: dict[str, Any]):
        user = self.repo.create_user(payload)
        self.session.commit()
        self.session.refresh(user)
        return user

    def create_project(self, payload: dict[str, Any]):
        project = self.repo.create_project(payload)
        self.session.commit()
        self.session.refresh(project)
        return project

    def create_sample(self, payload: dict[str, Any], with_blank_records: bool = True):
        sample = self.repo.create_sample(payload)
        if with_blank_records:
            self.repo.create_blank_prep(sample_nr=sample.sample_nr, prep_nr=1)
            self.repo.create_blank_target(sample_nr=sample.sample_nr, prep_nr=1, target_nr=1)
        self.session.commit()
        self.session.refresh(sample)
        return sample

    def add_new_project_by_user_nr(self, user_nr: int, project_name: str):
        project_name = TextSanitizer.replace_bad_characters(project_name)
        today = date.today()
        payload = {
            "project": project_name,
            "user_nr": user_nr,
            "in_date": today,
            "desired_date": today + timedelta(days=90),
            "status": "planned",
            "out_date": None,
        }
        return self.create_project(payload)

    def add_new_sample_by_project_nr(self, project_nr: int, sample_name: str):
        sample_name = TextSanitizer.replace_bad_characters(sample_name)
        payload = {
            "project_nr": project_nr,
            "user_label": sample_name,
        }
        return self.create_sample(payload, with_blank_records=True)

    def create_next_prep_for_sample(self, sample_nr: int) -> tuple[int, int]:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            raise ValueError("Sample not found.")
        _, max_prep_nr = self.repo.get_preparation_stats(sample_nr)
        next_prep_nr = int(max_prep_nr or 0) + 1
        self.repo.create_blank_prep(sample_nr=sample_nr, prep_nr=next_prep_nr)
        self.repo.create_blank_target(sample_nr=sample_nr, prep_nr=next_prep_nr, target_nr=1)
        self.session.commit()
        return next_prep_nr, 1

    def create_next_target_for_sample_prep(self, sample_nr: int, prep_nr: int) -> int:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            raise ValueError("Sample not found.")
        preparation = self.repo.get_preparation(sample_nr, prep_nr)
        if preparation is None:
            raise ValueError("Preparation not found.")
        _, max_target_nr = self.repo.get_target_stats(sample_nr, prep_nr)
        next_target_nr = int(max_target_nr or 0) + 1
        self.repo.create_blank_target(sample_nr=sample_nr, prep_nr=prep_nr, target_nr=next_target_nr)
        self.session.commit()
        return next_target_nr

    def set_project_running(self, sample_nr: int) -> bool:
        changed = self.repo.set_project_running_by_sample(sample_nr)
        if changed:
            self.session.commit()
        return changed

    def transfer_age_from_target(self, sample_nr: int, prep_nr: int = 1, target_nr: int = 1) -> bool:
        changed = self.repo.transfer_age_from_target(sample_nr, prep_nr, target_nr)
        if changed:
            self.session.commit()
        return changed

    def check_project_status(self) -> int:
        closed_count = self.repo.check_project_status()
        if closed_count > 0:
            self.session.commit()
        return closed_count

    def get_lookups(self) -> dict[str, list[str]]:
        return {
            "materials": self.repo.get_materials(),
            "fractions": self.repo.get_fractions(),
            "methods": self.repo.get_methods(),
            "sample_types": self.repo.get_sample_types(),
        }

    def get_standard_thresholds(self) -> dict[str, dict[str, int]]:
        return ThresholdStore.as_payload(self.threshold_store.load())

    def update_standard_thresholds(
        self, payload: dict[str, dict[str, Any]]
    ) -> dict[str, dict[str, int]]:
        return ThresholdStore.as_payload(self.threshold_store.update(payload))

    def list_setup_sections(self) -> list[dict[str, Any]]:
        return [
            {
                "key": section.key,
                "title": section.title,
                "description": section.description,
                "editable": section.editable,
                "status": section.status,
                "form_action": section.form_action,
            }
            for section in SETUP_SECTIONS
        ]

    def get_setup_section(self, section_key: str | None = None) -> dict[str, Any]:
        effective_key = section_key or SETUP_SECTIONS[0].key
        section = SETUP_SECTION_MAP.get(effective_key)
        if section is None:
            raise ValueError(f"Unknown setup section: {effective_key}")

        base_payload = {
            "key": section.key,
            "title": section.title,
            "description": section.description,
            "editable": section.editable,
            "status": section.status,
            "form_action": section.form_action,
            "storage_file": str(self.setup_store.path),
        }
        if section.key == SETUP_SECTION_STANDARD_THRESHOLDS:
            return {
                **base_payload,
                "kind": "threshold_matrix",
                "storage_section": self.threshold_store.section_key,
                "thresholds": self.get_standard_thresholds(),
                "threshold_fields": THRESHOLD_FIELDS,
            }
        if section.key == SETUP_SECTION_GRAPHITIZATION_SYSTEMS:
            systems = self.get_graphitization_systems()
            return {
                **base_payload,
                "kind": "string_list",
                "storage_section": section.key,
                "list_items": systems,
                "list_text": "\n".join(systems),
                "list_label": "Systems",
                "list_placeholder": "One system per line (e.g. mag)",
                "list_help": "Used as the suffix in graph batch names: graph_YYMMDD_system",
            }

        return {
            **base_payload,
            "kind": "placeholder",
            "storage_section": section.key,
            "data": self.setup_store.get_section(section.key, default={}),
        }

    def update_setup_section(
        self,
        section_key: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        section = SETUP_SECTION_MAP.get(section_key)
        if section is None:
            raise ValueError(f"Unknown setup section: {section_key}")
        if not section.editable:
            raise ValueError("This setup section is not editable yet.")
        if section.key == SETUP_SECTION_STANDARD_THRESHOLDS:
            return {
                "kind": "threshold_matrix",
                "thresholds": self.update_standard_thresholds(payload),
                "threshold_fields": THRESHOLD_FIELDS,
                "storage_file": str(self.setup_store.path),
                "storage_section": self.threshold_store.section_key,
            }
        if section.key == SETUP_SECTION_GRAPHITIZATION_SYSTEMS:
            items_raw = payload.get("items")
            if not isinstance(items_raw, list):
                raise ValueError("Graphitization systems payload must contain a list of items.")
            cleaned: list[str] = []
            seen: set[str] = set()
            for index, item in enumerate(items_raw, start=1):
                if not isinstance(item, str):
                    raise ValueError(f"System entry {index} must be text.")
                value = item.strip()
                if value == "":
                    continue
                if not GRAPHITIZATION_SYSTEM_VALUE_PATTERN.fullmatch(value):
                    raise ValueError(
                        f"Invalid system '{value}'. Use only letters, numbers, dot, dash, and underscore."
                    )
                if value in seen:
                    raise ValueError(f"Duplicate system '{value}' is not allowed.")
                cleaned.append(value)
                seen.add(value)
            if not cleaned:
                raise ValueError("At least one graphitization system is required.")
            self.setup_store.set_section(section.key, cleaned)
            return {
                "kind": "string_list",
                "storage_file": str(self.setup_store.path),
                "storage_section": section.key,
                "list_items": cleaned,
                "list_text": "\n".join(cleaned),
            }
        raise ValueError("No update handler configured for this setup section.")

    @staticmethod
    def _standard_statuses(
        standards: dict[str, int],
        thresholds: dict[str, ThresholdRule],
    ) -> dict[str, str]:
        return {
            key: rule.classify(standards.get(key, 0))
            for key, rule in thresholds.items()
        }

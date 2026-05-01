"""Service layer for SAMS business workflows."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any

from sqlalchemy.orm import Session

from sams_web.detail_update import DetailUpdateConfig, apply_detail_update
from sams_web.models import Preparation, Project, Sample, Target, Submitter
from sams_web.repositories import SamsRepository
from sams_web.viewmodels.detail_sections_sample_lab import (
    PREPARATION_DETAIL,
    SAMPLE_DETAIL,
    TARGET_DETAIL,
)
from sams_web.viewmodels.detail_sections_user_project import (
    PROJECT_DETAIL,
    SUBMITTER_DETAIL,
)
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

    def list_submitters(self, query: str | None = None, limit: int | None = None):
        return self.repo.list_submitters(query=query, limit=limit)

    def get_submitter_details(self, user_nr: int):
        user = self.repo.get_submitter(user_nr)
        if user is None:
            return None
        previous_user_nr, next_user_nr = self.repo.get_adjacent_submitter_nrs(user_nr)
        user_count, max_user_nr = self.repo.get_submitter_stats()
        return {
            "user": user,
            "projects": self.repo.list_projects_by_submitter(user_nr),
            "previous_user_nr": previous_user_nr,
            "next_user_nr": next_user_nr,
            "user_count": user_count,
            "max_user_nr": max_user_nr,
        }

    def _apply_and_commit(
        self,
        config: "DetailUpdateConfig",
        entity_nr: Any,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        # Thin shim: deep module flushes; this method commits on success.
        result = apply_detail_update(config, entity_nr, submitted_fields, self.repo)
        if result.saved:
            try:
                self.session.commit()
            except Exception:
                self.session.rollback()
                raise
            return True, {}, None
        save_error = result.save_error
        if save_error is None and result.field_errors:
            save_error = "Please correct the highlighted fields and save again."
        return False, result.field_errors, save_error

    def update_submitter_detail(
        self,
        user_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        return self._apply_and_commit(SUBMITTER_DETAIL, user_nr, submitted_fields)

    def get_submitter_projects(self, user_nr: int):
        data = self.get_submitter_details(user_nr)
        if data is None:
            return None
        return data

    def list_projects(self, limit: int | None = None):
        return self.repo.list_projects(limit=limit)

    def get_project_details(self, project_nr: int):
        project = self.repo.get_project(project_nr)
        if project is None:
            return None
        user = self.repo.get_submitter(project.user_nr) if project.user_nr else None
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
        return self._apply_and_commit(PROJECT_DETAIL, project_nr, submitted_fields)

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

    def get_samples_landing(self, preferred_sample_nr: int | None = None) -> dict[str, Any]:
        """Data for the /samples landing page: last visited (if valid),
        newest sample, and the total count.

        `last_sample_nr` is the operator's cookie-recorded most-recent sample
        if it still exists in the DB; otherwise None. `newest_sample_nr` is
        the highest sample_nr in the database (effectively "most recent
        record"). Both may be the same number — the route shows "Resume" only
        when the cookie value differs from the newest, to avoid two buttons
        for the same destination.
        """
        sample_count, max_sample_nr = self.repo.get_sample_stats()
        last_sample_nr: int | None = None
        if (
            preferred_sample_nr is not None
            and preferred_sample_nr > 0
            and self.sample_exists(preferred_sample_nr)
        ):
            last_sample_nr = preferred_sample_nr
        return {
            "last_sample_nr": last_sample_nr,
            "newest_sample_nr": max_sample_nr if max_sample_nr > 0 else None,
            "sample_count": sample_count,
        }

    def preparation_exists(self, sample_nr: int, prep_nr: int) -> bool:
        return self.repo.get_preparation(sample_nr, prep_nr) is not None

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
        return self._apply_and_commit(PREPARATION_DETAIL, (sample_nr, prep_nr), submitted_fields)

    def update_target_detail(
        self,
        sample_nr: int,
        prep_nr: int,
        target_nr: int,
        submitted_fields: dict[str, str],
    ) -> tuple[bool, dict[str, str], str | None]:
        return self._apply_and_commit(
            TARGET_DETAIL, (sample_nr, prep_nr, target_nr), submitted_fields
        )

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

    def submitter_exists(self, user_nr: int) -> bool:
        return self.repo.get_submitter(user_nr) is not None

    def get_sample_overview(
        self,
        sample_nr: int,
    ) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None

        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_submitter(project.user_nr) if project and project.user_nr else None
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
        return self._apply_and_commit(SAMPLE_DETAIL, sample_nr, submitted_fields)

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
        user = self.repo.get_submitter(project.user_nr) if project and project.user_nr else None
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
        user = self.repo.get_submitter(project.user_nr) if project and project.user_nr else None
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
        from sams_web.search import run_search
        return run_search(self.session, context_name=context, phrase=phrase, limit=limit)

    def create_submitter(self, payload: dict[str, Any]):
        user = self.repo.create_submitter(payload)
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

    def add_new_project_by_submitter_nr(self, user_nr: int, project_name: str):
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

"""Shared context builders and edit constants for detail page routers."""

from __future__ import annotations

from urllib.parse import quote_plus

from fastapi import Request

from sams_web.services import SamsService
from sams_web.viewmodels import detail_sections as ds

SAMPLE_EDIT_FORM_ID = "sample-detail-edit-form"
SAMPLE_READ_ONLY_FIELDS = ("sample_nr", "project_nr")
SAMPLE_REQUIRED_FIELDS = (
    "sample__type",
    "sample__material",
    "sample__fraction",
    "sample__project_in_date",
    "sample__project_desired_date",
)
PREPARATION_EDIT_FORM_ID = "preparation-detail-edit-form"
PREPARATION_READ_ONLY_FIELDS = ("sample_nr", "prep_nr")
PREPARATION_REQUIRED_FIELDS: tuple[str, ...] = ()
TARGET_EDIT_FORM_ID = "target-detail-edit-form"
TARGET_READ_ONLY_FIELDS = ("sample_nr", "prep_nr", "target_nr", "target_id")
TARGET_REQUIRED_FIELDS: tuple[str, ...] = ()


def build_sample_detail_context(
    request: Request,
    *,
    overview: dict[str, object],
    service: SamsService,
    saved: bool = False,
    save_error: str | None = None,
    sample_field_errors: dict[str, str] | None = None,
    sample_form_values: dict[str, str] | None = None,
    sample_edit_initial_mode: str = "view",
    creation_notice: str | None = None,
) -> dict[str, object]:
    sample = overview["sample"]
    project = overview["project"]
    preparations = overview["preparations"]
    default_target_prep_nr = preparations[0].prep_nr if preparations else None

    return {
        "request": request,
        "sample": sample,
        "project": project,
        "user": overview["user"],
        "preparations": preparations,
        "targets_by_prep": overview["targets_by_prep"],
        "sample_targets_total": overview["sample_targets_total"],
        "targets": overview["targets"],
        "previous_sample_nr": overview["previous_sample_nr"],
        "next_sample_nr": overview["next_sample_nr"],
        "sample_count": overview["sample_count"],
        "max_sample_nr": overview["max_sample_nr"],
        "sample_sections": ds.build_sample_sections(sample, project=project),
        "sample_c14_age_display": ds.format_sample_value("c14_age", sample.c14_age),
        "sample_user_comment_display": ds.format_sample_value("user_comment", sample.user_comment),
        "sample_lab_comment_display": ds.format_sample_value("lab_comment", sample.lab_comment),
        "sample_edit_form_id": SAMPLE_EDIT_FORM_ID,
        "sample_read_only_fields": SAMPLE_READ_ONLY_FIELDS,
        "sample_required_fields": SAMPLE_REQUIRED_FIELDS,
        "sample_select_options": service.get_sample_edit_select_options(),
        "sample_field_errors": sample_field_errors or {},
        "sample_form_values": sample_form_values or {},
        "sample_save_error": save_error,
        "sample_saved": saved,
        "sample_edit_initial_mode": sample_edit_initial_mode,
        "sample_creation_notice": creation_notice,
        "sample_default_target_prep_nr": default_target_prep_nr,
    }


def build_preparation_detail_context(
    request: Request,
    *,
    data: dict[str, object],
    service: SamsService,
    saved: bool = False,
    save_error: str | None = None,
    preparation_field_errors: dict[str, str] | None = None,
    preparation_form_values: dict[str, str] | None = None,
    preparation_edit_initial_mode: str = "view",
) -> dict[str, object]:
    return {
        "request": request,
        "sample": data["sample"],
        "project": data["project"],
        "user": data["user"],
        "preparation": data["preparation"],
        "preparation_sections": ds.build_preparation_sections(data["preparation"]),
        "targets": data["targets"],
        "targets_total": data["targets_total"],
        "previous_prep_nr": data["previous_prep_nr"],
        "next_prep_nr": data["next_prep_nr"],
        "preparation_count": data["preparation_count"],
        "max_prep_nr": data["max_prep_nr"],
        "preparation_edit_form_id": PREPARATION_EDIT_FORM_ID,
        "preparation_read_only_fields": PREPARATION_READ_ONLY_FIELDS,
        "preparation_required_fields": PREPARATION_REQUIRED_FIELDS,
        "preparation_select_options": service.get_preparation_edit_select_options(),
        "preparation_field_errors": preparation_field_errors or {},
        "preparation_form_values": preparation_form_values or {},
        "preparation_save_error": save_error,
        "preparation_saved": saved,
        "preparation_edit_initial_mode": preparation_edit_initial_mode,
    }


def build_target_detail_context(
    request: Request,
    *,
    sample_nr: int,
    prep_nr: int,
    target_nr: int,
    data: dict[str, object],
    saved: bool = False,
    save_error: str | None = None,
    target_field_errors: dict[str, str] | None = None,
    target_form_values: dict[str, str] | None = None,
    target_edit_initial_mode: str = "view",
) -> dict[str, object]:
    target = data["target"]
    target_sections = ds.build_target_sections(target)
    for section in target_sections:
        for row in section.get("rows", []):
            if row.get("key") != "magazine":
                continue
            raw_magazine = row.get("raw_value")
            if raw_magazine is None:
                continue
            magazine_value = str(raw_magazine).strip()
            if magazine_value == "":
                continue
            row["action_url"] = f"/lab/analysis?magazine={quote_plus(magazine_value)}#tbl-magazine-targets"
            row["action_title"] = f"Show all targets in magazine {magazine_value}"

    return {
        "request": request,
        "sample": data["sample"],
        "project": data["project"],
        "user": data["user"],
        "preparation": data["preparation"],
        "target": target,
        "target_prep_options": data.get("preparations", []),
        "target_sections": target_sections,
        "previous_target_nr": data["previous_target_nr"],
        "next_target_nr": data["next_target_nr"],
        "target_count": data["target_count"],
        "max_target_nr": data["max_target_nr"],
        "target_fm_display": ds.format_target_indicator("fm", target.fm),
        "target_fm_sig_display": ds.format_target_indicator("fm_sig", target.fm_sig),
        "target_dc13_display": ds.format_target_indicator("dc13", target.dc13),
        "target_c14_age_display": ds.format_target_indicator("c14_age", target.c14_age),
        "target_c14_age_sig_display": ds.format_target_indicator("c14_age_sig", target.c14_age_sig),
        "target_edit_form_id": TARGET_EDIT_FORM_ID,
        "target_read_only_fields": TARGET_READ_ONLY_FIELDS,
        "target_required_fields": TARGET_REQUIRED_FIELDS,
        "target_select_options": {},
        "target_field_errors": target_field_errors or {},
        "target_form_values": target_form_values or {},
        "target_save_error": save_error,
        "target_saved": saved,
        "target_edit_initial_mode": target_edit_initial_mode,
        "sample_nr": sample_nr,
        "prep_nr": prep_nr,
        "target_nr": target_nr,
    }


def build_sample_creation_notice(
    *,
    created: str | None,
    created_prep: int | None,
    created_target: int | None,
) -> str | None:
    if created == "prep" and created_prep is not None:
        return f"Created preparation #{created_prep} and seeded target #1."
    if created == "target" and created_prep is not None and created_target is not None:
        return f"Created target #{created_target} in preparation #{created_prep}."
    return None

"""Sample, preparation, and target detail section definitions, plus their detail-update configs."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from urllib.parse import quote_plus

from sams_web.detail_page import DetailPageConfig
from sams_web.field_labels import field_label
from sams_web.detail_update import DetailUpdateConfig, RelatedEntityRule
from sams_web.models import Preparation, Sample, Target
from sams_web.viewmodels.detail_sections_user_project import PROJECT_DETAIL
from sams_web.viewmodels.lab_warnings import (
    evaluate_preparation_warnings,
    evaluate_target_warnings,
)
from sams_web.viewmodels.detail_sections_common import (
    Row,
    SectionSpec,
    arrange_sections,
    attach_readout,
    build_sections,
    format_c14_integer,
    format_cn_ratio,
    format_cn_ratio_from_conc,
    format_d13c,
    format_one_decimal,
    format_total_c_ug,
    is_empty_display_value,
    mapped_values,
)


# One list of sections per entity: the first ones form the fact sheet at
# the top of the page, the rest fold into "More details" (see
# SAMPLE_MORE_SECTIONS). The sample number and project are in the page
# title and context line, so they are not repeated as rows.
SAMPLE_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Identity", "", ("user_label", "user_label_nr", "user_desc1", "user_desc2")),
    ("Classification", "", ("type", "material", "fraction", "weight")),
    ("Results", "", ("c14_age", "c14_age_sig", "av_fm", "av_fm_sig", "av_dc13", "av_dc13_sig")),
    ("Comments", "", ("user_comment", "lab_comment")),
    ("Record", "", ("photo", "editable", "ma_nr")),
    ("Dates", "", ("sampling_date",)),
    ("Lab Workflow", "", ("not_tobedated", "pre_sub_treat", "preparation", "residue")),
    ("Calibration", "", ("delta_r", "calib", "cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max")),
    ("Storage", "", ("s_no_leftover", "s_storage_loc", "prep_storage_loc")),
)
SAMPLE_SECTION_ORDER = ("Identity", "Classification", "Other Analysis", "Results", "Comments")
SAMPLE_WIDE_SECTIONS = frozenset({"Comments"})
SAMPLE_MORE_SECTIONS = frozenset({"Record", "Dates", "Lab Workflow", "Calibration", "Storage"})
# Label above value: sample labels average 20 characters (max 94).
SAMPLE_STACKED_FIELDS = frozenset({"user_label", "user_label_nr"})

SAMPLE_PROJECT_SUBMISSION_KEYS: tuple[str, ...] = ("in_date", "desired_date", "out_date")
SAMPLE_BOOLEAN_FIELDS = {"editable", "not_tobedated", "s_no_leftover", "c_n_isotop_a", "c_n_isotop_a_moved", "dendro_a"}
SAMPLE_EXCLUDED_FIELDS = {"old_info", "storage", "left_over", "sample_nr", "project_nr"}


def sample_field_kind(key: str) -> str:
    if key in SAMPLE_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"user_comment", "lab_comment", "old_info", "user_desc1", "user_desc2"}:
        return "multiline"
    if "date" in key or key.endswith("_date"):
        return "date"
    return "text"


def format_sample_value(key: str, value: Any) -> Any:
    if is_empty_display_value(value):
        return None
    if isinstance(value, str):
        value = value.strip()
    if key in {"av_fm", "av_fm_sig", "av_dc13", "av_dc13_sig"}:
        try:
            rounded_4 = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return value
        return format(rounded_4, "f")
    if key in {"c14_age", "c14_age_sig"}:
        return format_c14_integer(value)
    if key in SAMPLE_BOOLEAN_FIELDS:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    return value


def build_sample_sections(sample: Any, project: Any | None = None) -> list[dict[str, Any]]:
    project_values = mapped_values(project) if project is not None else {}

    def extra_rows(section_title: str) -> Iterable[Row]:
        if section_title != "Dates" or not project_values:
            return []
        return [
            {
                "key": f"project_{project_key}",
                "label": field_label(f"project_{project_key}"),
                "kind": "date",
                "raw_value": project_values.get(project_key),
                "value": format_sample_value(project_key, project_values.get(project_key)),
            }
            for project_key in SAMPLE_PROJECT_SUBMISSION_KEYS
        ]

    sections = build_sections(
        sample,
        section_specs=SAMPLE_SECTION_SPECS,
        kind_resolver=sample_field_kind,
        value_formatter=format_sample_value,
        include_other=True,
        other_title="Other Analysis",
        other_description="",
        other_excluded_keys=SAMPLE_EXCLUDED_FIELDS,
        extra_rows_by_section=extra_rows,
        drop_all_empty_sections=True,
    )
    attach_readout(
        sections, section_title="Results", value_key="c14_age", sigma_key="c14_age_sig", label=field_label("c14_age")
    )
    return arrange_sections(
        sections,
        order=SAMPLE_SECTION_ORDER,
        wide=SAMPLE_WIDE_SECTIONS,
        more=SAMPLE_MORE_SECTIONS,
        stacked=SAMPLE_STACKED_FIELDS,
    )



PREPARATION_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Batch & Timeline", "", ("batch", "prep_start", "prep_end", "stop", "p_no_leftover")),
    ("Weights and Methods", "", ("weight_start", "step1_method", "step2_method", "step3_method", "step4_method", "step5_method", "weight_medium", "weight_medium_2", "weight_end")),
    ("Step Timeline", "", ("step1_start", "step1_end", "step2_start", "step2_end", "step3_start", "step3_end", "step4_start", "step4_end", "step5_start", "step5_end")),
    ("EA Data", "", ("c_percent", "n_percent", "cn_ratio")),
    ("Comments", "", ("prep_comment", "old_info")),
)
PREPARATION_WIDE_SECTIONS = frozenset({"Comments"})
# Prep batch names average 18 characters (max 39).
PREPARATION_STACKED_FIELDS = frozenset({"batch"})

PREPARATION_BOOLEAN_FIELDS = {"stop", "p_no_leftover"}
PREPARATION_EXCLUDED_FIELDS = {"left_over", "sample_nr", "prep_nr"}


def preparation_field_kind(key: str) -> str:
    if key in PREPARATION_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"prep_comment", "old_info"}:
        return "multiline"
    if key in {"prep_start", "prep_end"}:
        return "date"
    if key.startswith("step") and (key.endswith("_start") or key.endswith("_end")):
        return "date"
    return "text"


def format_preparation_value(key: str, value: Any) -> Any:
    if is_empty_display_value(value):
        return None
    if isinstance(value, str):
        value = value.strip()
    if key in PREPARATION_BOOLEAN_FIELDS:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    if key == "cn_ratio":
        return format_cn_ratio(value)
    return value


def calculate_preparation_yield(weight_start: Any, weight_end: Any) -> str | None:
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


def build_preparation_sections(preparation: Any) -> list[dict[str, Any]]:
    values_by_key = mapped_values(preparation)

    def extra_rows(section_title: str) -> Iterable[Row]:
        if section_title != "Weights and Methods":
            return []
        yield_value = calculate_preparation_yield(values_by_key.get("weight_start"), values_by_key.get("weight_end"))
        return [
            {
                "key": "yield_percent",
                "label": field_label("yield_percent"),
                "kind": "text",
                "raw_value": yield_value,
                "value": yield_value,
                "read_only": True,
            }
        ]

    sections = build_sections(
        preparation,
        section_specs=PREPARATION_SECTION_SPECS,
        kind_resolver=preparation_field_kind,
        value_formatter=format_preparation_value,
        include_other=True,
        other_title="Other",
        other_description="",
        other_excluded_keys=PREPARATION_EXCLUDED_FIELDS,
        extra_rows_by_section=extra_rows,
    )
    for section in sections:
        if section.get("title") != "Weights and Methods":
            continue
        for row in section.get("rows", []):
            key = row.get("key")
            if key == "step1_method":
                row["divider_before"] = True
            elif key == "step5_method":
                row["divider_after"] = True
        weight_end_index = next((idx for idx, row in enumerate(section.get("rows", [])) if row.get("key") == "weight_end"), None)
        yield_index = next((idx for idx, row in enumerate(section.get("rows", [])) if row.get("key") == "yield_percent"), None)
        if weight_end_index is not None and yield_index is not None and yield_index != weight_end_index + 1:
            yield_row = section["rows"].pop(yield_index)
            insert_at = weight_end_index + 1
            if yield_index < insert_at:
                insert_at -= 1
            section["rows"].insert(insert_at, yield_row)
    return arrange_sections(sections, wide=PREPARATION_WIDE_SECTIONS, stacked=PREPARATION_STACKED_FIELDS)



# Sample / prep / target numbers and the target ID are in the page title
# and context line, so the old "Main Info" section is gone.
TARGET_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Graphitization", "", ("graph_batch", "reactor_nr", "co2_init", "co2_final", "hydro_init", "hydro_final", "react_time", "temp", "graphitized", "target_pressed", "stop")),
    ("Elemental Analysis", "", ("weight_combustion", "conc_c", "conc_n")),
    ("Results", "", ("c14_age", "c14_age_sig", "fm", "fm_sig", "dc13", "dc13_sig", "magazine", "position", "calcset", "le_curr", "he_curr")),
    ("Calibration", "", ("cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max")),
    ("Comments", "", ("target_comment", "meas_comment")),
)
TARGET_WIDE_SECTIONS = frozenset({"Comments"})
# Graph batch names average 16 characters (max 29).
TARGET_STACKED_FIELDS = frozenset({"graph_batch"})

TARGET_BOOLEAN_FIELDS = {"stop"}


def target_field_kind(key: str) -> str:
    if key in TARGET_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"target_comment", "meas_comment"}:
        return "multiline"
    if key in {"graphitized", "target_pressed"}:
        return "date"
    if key in {"graph_date"}:
        return "datetime"
    return "text"


def format_target_indicator(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in {"fm", "fm_sig"}:
        try:
            rounded_4 = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return value
        return format(rounded_4, "f")
    if key in {"dc13", "dc13_sig"}:
        return format_d13c(value)
    if key in {"c14_age", "c14_age_sig"}:
        return format_c14_integer(value)
    return value


def format_target_value(key: str, value: Any) -> Any:
    if is_empty_display_value(value):
        return None
    if isinstance(value, str):
        value = value.strip()
    if key in TARGET_BOOLEAN_FIELDS:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    if key in {"conc_c", "conc_n"}:
        return format_one_decimal(value)
    if key in {"fm", "fm_sig", "dc13", "dc13_sig", "c14_age", "c14_age_sig"}:
        return format_target_indicator(key, value)
    return value


def build_target_sections(target: Any) -> list[dict[str, Any]]:
    values_by_key = mapped_values(target)

    def extra_rows(section_title: str) -> Iterable[Row]:
        if section_title != "Elemental Analysis":
            return []
        ratio = format_cn_ratio_from_conc(values_by_key.get("conc_c"), values_by_key.get("conc_n"))
        total_c_ug = format_total_c_ug(
            values_by_key.get("weight_combustion"), values_by_key.get("conc_c")
        )
        return [
            {
                "key": "cn_ratio_calc",
                "label": field_label("cn_ratio_calc"),
                "kind": "text",
                "raw_value": ratio,
                "value": ratio,
                "read_only": True,
            },
            {
                "key": "total_c_ug",
                "label": field_label("total_c_ug"),
                "kind": "text",
                "raw_value": total_c_ug,
                "value": total_c_ug,
                "read_only": True,
            },
        ]

    sections = build_sections(
        target,
        section_specs=TARGET_SECTION_SPECS,
        kind_resolver=target_field_kind,
        value_formatter=format_target_value,
        include_other=False,
        extra_rows_by_section=extra_rows,
    )
    for section in sections:
        title = section.get("title")
        if title == "Graphitization":
            for row in section.get("rows", []):
                if row.get("key") in {"reactor_nr", "graphitized"}:
                    row["divider_before"] = True
        elif title == "Results":
            for row in section.get("rows", []):
                if row.get("key") == "magazine":
                    row["divider_before"] = True
    attach_readout(
        sections, section_title="Results", value_key="c14_age", sigma_key="c14_age_sig", label=field_label("c14_age")
    )
    return arrange_sections(sections, wide=TARGET_WIDE_SECTIONS, stacked=TARGET_STACKED_FIELDS)


# ---- Detail-update configs ------------------------------------------------

# Per ADR-0003: BATS owns these target_t fields; webSAMS detail-update paths
# must never write to them. Listed here for use in TARGET_DETAIL.read_only_fields.
_BATS_OWNED_TARGET_FIELDS: frozenset[str] = frozenset({
    "fm", "fm_sig",
    "dc13", "dc13_sig",
    "c14_age", "c14_age_sig",
    "cal1s_min", "cal1s_max",
    "cal2s_min", "cal2s_max",
    "calcset",
    "editallowed",
})

# Per ADR-0003: BATS-derived sample_t fields. Direct edits via the detail-
# update path are blocked. The Transfer-to-Sample workflow (ADR-0002) writes
# some of these by copying BATS-evaluated target values to the sample row.
_BATS_OWNED_SAMPLE_FIELDS: frozenset[str] = frozenset({
    "editable",
    "calib",
    "delta_r",
    "c14_age", "c14_age_sig",
    "av_fm", "av_fm_sig",
    "av_dc13", "av_dc13_sig",
    "cal1s_min", "cal1s_max",
    "cal2s_min", "cal2s_max",
})


def _methods_dropdown(repo: Any) -> list[str]:
    return list(repo.get_methods())


PREPARATION_DETAIL = DetailUpdateConfig(
    model=Preparation,
    prefix="preparation__",
    read_only_fields=frozenset({"sample_nr", "prep_nr", "yield_percent"}),
    dropdown_getters={
        "step1_method": _methods_dropdown,
        "step2_method": _methods_dropdown,
        "step3_method": _methods_dropdown,
        "step4_method": _methods_dropdown,
        "step5_method": _methods_dropdown,
    },
)


TARGET_DETAIL = DetailUpdateConfig(
    model=Target,
    prefix="target__",
    read_only_fields=frozenset({"sample_nr", "prep_nr", "target_nr", "target_id"}) | _BATS_OWNED_TARGET_FIELDS,
)


SAMPLE_DETAIL = DetailUpdateConfig(
    model=Sample,
    prefix="sample__",
    read_only_fields=frozenset({"sample_nr", "project_nr"}) | _BATS_OWNED_SAMPLE_FIELDS,
    dropdown_getters={
        "type": lambda repo: list(repo.get_sample_types()),
        "material": lambda repo: list(repo.get_materials()),
        "fraction": lambda repo: list(repo.get_fractions()),
    },
    required_fields=(
        ("type", "Type is required."),
        ("material", "Material is required."),
        ("fraction", "Fraction is required."),
    ),
    related=(
        RelatedEntityRule(
            prefix="project_",
            config=PROJECT_DETAIL,
            lookup=lambda sample, repo: (
                repo.get_project(sample.project_nr) if sample.project_nr else None
            ),
            missing_error="This sample has no linked project.",
            extra_required_fields=(
                ("in_date", f"{field_label('project_in_date')} is required."),
                ("desired_date", f"{field_label('project_desired_date')} is required."),
            ),
        ),
    ),
)


# ---- Detail-page configs (read side) -------------------------------------


def _decorate_target_sections_with_magazine_links(target: Any) -> list[dict[str, Any]]:
    """Build target sections, then decorate the `magazine` row with a deep
    link to `/lab/analysis?magazine=<value>` so operators can jump directly
    from a target to the magazine listing it belongs to."""
    sections = build_target_sections(target)
    for section in sections:
        for row in section.get("rows", []):
            if row.get("key") != "magazine":
                continue
            raw_magazine = row.get("raw_value")
            if raw_magazine is None:
                continue
            magazine_value = str(raw_magazine).strip()
            if magazine_value == "":
                continue
            row["action_url"] = (
                f"/lab/analysis?magazine={quote_plus(magazine_value)}#tbl-magazine-targets"
            )
            row["action_title"] = f"Show all targets in magazine {magazine_value}"
    return sections


SAMPLE_DETAIL_PAGE = DetailPageConfig(
    name="sample",
    update_config=SAMPLE_DETAIL,
    edit_form_id="sample-detail-edit-form",
    sections_builder=build_sample_sections,
    select_options_getter=lambda service: service.get_sample_edit_select_options(),
)


PREPARATION_DETAIL_PAGE = DetailPageConfig(
    name="preparation",
    update_config=PREPARATION_DETAIL,
    edit_form_id="preparation-detail-edit-form",
    sections_builder=build_preparation_sections,
    select_options_getter=lambda service: service.get_preparation_edit_select_options(),
    warnings_builder=evaluate_preparation_warnings,
)


TARGET_DETAIL_PAGE = DetailPageConfig(
    name="target",
    update_config=TARGET_DETAIL,
    edit_form_id="target-detail-edit-form",
    sections_builder=_decorate_target_sections_with_magazine_links,
    warnings_builder=evaluate_target_warnings,
)

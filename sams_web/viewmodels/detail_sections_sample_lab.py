"""Sample, preparation, and target detail section definitions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable

from sams_web.viewmodels.detail_sections_common import (
    Row,
    SectionSpec,
    build_sections,
    format_c14_integer,
    format_cn_ratio,
    format_cn_ratio_from_conc,
    format_d13c,
    format_one_decimal,
    mapped_values,
)

SAMPLE_FIELD_LABELS = {
    "sample_nr": "Sample #",
    "project_nr": "Project #",
    "project_in_date": "Project In Date",
    "project_desired_date": "Project Desired Date",
    "project_out_date": "Project Out Date",
    "user_label": "Sample Label",
    "user_label_nr": "Sample Label #",
    "type": "Type",
    "material": "Material",
    "fraction": "Fraction",
    "sampling_date": "Sampling Date",
    "photo": "Photo",
    "user_desc1": "Description 1",
    "user_desc2": "Description 2",
    "user_comment": "User Comment",
    "pre_sub_treat": "Pre-sub Treatment",
    "preparation": "Preparation",
    "editable": "Editable",
    "not_tobedated": "Not To Be Dated",
    "residue": "Residue",
    "lab_comment": "Lab Comment",
    "weight": "Weight",
    "c14_age": "C14 Age",
    "c14_age_sig": "C14 Sigma",
    "av_fm": "Average Fm",
    "av_fm_sig": "Average Fm Sigma",
    "av_dc13": "Average d13C",
    "av_dc13_sig": "Average d13C Sigma",
    "delta_r": "Delta R",
    "calib": "Calibration",
    "cal1s_min": "Cal 1s Min",
    "cal1s_max": "Cal 1s Max",
    "cal2s_min": "Cal 2s Min",
    "cal2s_max": "Cal 2s Max",
    "storage": "Storage",
    "s_storage_loc": "Sample Storage Location",
    "prep_storage_loc": "Prep Storage Location",
    "left_over": "Leftover",
    "s_no_leftover": "No Leftover",
    "ma_nr": "MA #",
    "old_info": "Old Info",
    "c_n_isotop_a": "CN Isotop A",
    "c_n_isotop_a_moved": "CN Isotop A Moved",
}

SAMPLE_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Main Info", "Primary sample identity and core submission fields.", ("sample_nr", "project_nr", "photo", "type", "material", "fraction", "editable", "ma_nr")),
    ("Dates", "Submission context and project timeline.", ("sampling_date",)),
    ("Lab Workflow", "Preparation and laboratory workflow metadata.", ("not_tobedated", "pre_sub_treat", "preparation", "residue")),
    ("Measurements", "Measured values and calculated signal fields.", ("weight", "c14_age", "c14_age_sig", "av_fm", "av_fm_sig", "av_dc13", "av_dc13_sig", "delta_r", "calib")),
    ("Calibration", "Calibration ranges and limits.", ("cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max")),
    ("Storage", "Current location and leftovers.", ("s_no_leftover", "s_storage_loc", "prep_storage_loc")),
)

SAMPLE_PROJECT_SUBMISSION_KEYS: tuple[str, ...] = ("in_date", "desired_date", "out_date")
SAMPLE_BOOLEAN_FIELDS = {"editable", "not_tobedated", "s_no_leftover", "c_n_isotop_a", "c_n_isotop_a_moved"}
SAMPLE_EXCLUDED_FIELDS = {"old_info", "storage", "left_over", "user_comment", "lab_comment", "user_label", "user_label_nr", "user_desc1", "user_desc2"}


def sample_field_kind(key: str) -> str:
    if key in SAMPLE_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"user_comment", "lab_comment", "old_info", "user_desc1", "user_desc2"}:
        return "multiline"
    if "date" in key or key.endswith("_date"):
        return "date"
    return "text"


def format_sample_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
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
                "label": SAMPLE_FIELD_LABELS.get(f"project_{project_key}", f"Project {project_key.replace('_', ' ').title()}"),
                "kind": "date",
                "raw_value": project_values.get(project_key),
                "value": format_sample_value(project_key, project_values.get(project_key)),
            }
            for project_key in SAMPLE_PROJECT_SUBMISSION_KEYS
        ]

    return build_sections(
        sample,
        field_labels=SAMPLE_FIELD_LABELS,
        section_specs=SAMPLE_SECTION_SPECS,
        kind_resolver=sample_field_kind,
        value_formatter=format_sample_value,
        include_other=True,
        other_title="Other Analysis",
        other_description="Additional fields available in this sample record.",
        other_excluded_keys=SAMPLE_EXCLUDED_FIELDS,
        extra_rows_by_section=extra_rows,
    )


PREPARATION_FIELD_LABELS = {
    "sample_nr": "Sample #",
    "prep_nr": "Prep #",
    "batch": "Batch",
    "prep_start": "Prep Start",
    "prep_end": "Prep End",
    "stop": "Discarded",
    "prep_comment": "Preparation Comment",
    "weight_start": "Weight Start",
    "weight_medium": "Weight Mid",
    "weight_medium_2": "Weight Mid 2",
    "weight_end": "Weight End",
    "p_no_leftover": "No Leftover",
    "cn_ratio": "CN Ratio",
    "c_percent": "C %",
    "n_percent": "N %",
    "yield_percent": "Yield (%)",
    "step1_method": "Step 1 Method",
    "step1_start": "Step 1 Start",
    "step1_end": "Step 1 End",
    "step2_method": "Step 2 Method",
    "step2_start": "Step 2 Start",
    "step2_end": "Step 2 End",
    "step3_method": "Step 3 Method",
    "step3_start": "Step 3 Start",
    "step3_end": "Step 3 End",
    "step4_method": "Step 4 Method",
    "step4_start": "Step 4 Start",
    "step4_end": "Step 4 End",
    "step5_method": "Step 5 Method",
    "step5_start": "Step 5 Start",
    "step5_end": "Step 5 End",
    "old_info": "Old Info",
}

PREPARATION_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Main Info", "Preparation identity and current batch context.", ("sample_nr", "prep_nr", "batch", "stop", "p_no_leftover")),
    ("Weights and Methods", "Weight progression paired with step methods.", ("weight_start", "prep_start", "step1_method", "step2_method", "step3_method", "step4_method", "step5_method", "weight_medium", "weight_medium_2", "weight_end", "prep_end")),
    ("Step Timeline", "Start and end timestamps for each preparation step.", ("step1_start", "step1_end", "step2_start", "step2_end", "step3_start", "step3_end", "step4_start", "step4_end", "step5_start", "step5_end")),
    ("EA Data", "Elemental analyzer values and derived indicators.", ("c_percent", "n_percent", "cn_ratio")),
    ("Comments", "Preparation comments and legacy notes.", ("prep_comment", "old_info")),
)

PREPARATION_BOOLEAN_FIELDS = {"stop", "p_no_leftover"}
PREPARATION_EXCLUDED_FIELDS = {"left_over"}


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
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
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
                "label": PREPARATION_FIELD_LABELS["yield_percent"],
                "kind": "text",
                "raw_value": yield_value,
                "value": yield_value,
                "read_only": True,
            }
        ]

    sections = build_sections(
        preparation,
        field_labels=PREPARATION_FIELD_LABELS,
        section_specs=PREPARATION_SECTION_SPECS,
        kind_resolver=preparation_field_kind,
        value_formatter=format_preparation_value,
        include_other=True,
        other_title="Other",
        other_description="Additional fields available in this preparation record.",
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
    return sections


TARGET_FIELD_LABELS = {
    "sample_nr": "Sample #",
    "prep_nr": "Prep #",
    "target_nr": "Target #",
    "target_id": "Target ID",
    "graph_batch": "Graph Batch",
    "graph_date": "Graph Date",
    "graphitized": "Graphitized",
    "magazine": "Magazine",
    "position": "Position",
    "reactor_nr": "Reactor #",
    "co2_init": "CO2 Init",
    "co2_final": "CO2 Final",
    "hydro_init": "Hydrogen Init",
    "hydro_final": "Hydrogen Final",
    "react_time": "Reaction Time",
    "target_comment": "Target Comment",
    "target_pressed": "Target Pressed",
    "stop": "Discarded",
    "meas_comment": "Measurement Comment",
    "fm": "FM",
    "fm_sig": "FM Sigma",
    "dc13": "d13C",
    "dc13_sig": "d13C Sigma",
    "calcset": "Calcset",
    "c14_age": "C14 Age",
    "c14_age_sig": "C14 Sigma",
    "cal1s_min": "Cal 1s Min",
    "cal1s_max": "Cal 1s Max",
    "cal2s_min": "Cal 2s Min",
    "cal2s_max": "Cal 2s Max",
    "weight_combustion": "Weight Combustion",
    "weight": "Weight",
    "temp": "Temperature",
    "conc_c": "C (%)",
    "conc_n": "N (%)",
    "cn_ratio_calc": "C/N Ratio",
    "le_curr": "LE Current",
    "he_curr": "HE Current",
}

TARGET_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Main Info", "Target identity and assignment context.", ("sample_nr", "prep_nr", "target_nr", "target_id", "stop")),
    ("Graphitisation", "Graphitisation setup and execution metadata.", ("weight_combustion", "graph_batch", "reactor_nr", "co2_init", "co2_final", "hydro_init", "hydro_final", "react_time", "temp", "graphitized", "target_pressed")),
    ("Results", "Final radiocarbon and stable isotope results.", ("magazine", "position", "le_curr", "he_curr", "calcset", "fm", "fm_sig", "dc13", "dc13_sig", "c14_age", "c14_age_sig")),
    ("Calibration", "Calibration threshold windows and acceptance bands.", ("cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max")),
    ("Elemental Analyzer", "EA concentrations and current values.", ("conc_c", "conc_n")),
    ("Comments", "Target and measurement comments plus legacy notes.", ("target_comment", "meas_comment")),
)

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
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
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
        if section_title != "Elemental Analyzer":
            return []
        ratio = format_cn_ratio_from_conc(values_by_key.get("conc_c"), values_by_key.get("conc_n"))
        return [
            {
                "key": "cn_ratio_calc",
                "label": TARGET_FIELD_LABELS["cn_ratio_calc"],
                "kind": "text",
                "raw_value": ratio,
                "value": ratio,
                "read_only": True,
            }
        ]

    sections = build_sections(
        target,
        field_labels=TARGET_FIELD_LABELS,
        section_specs=TARGET_SECTION_SPECS,
        kind_resolver=target_field_kind,
        value_formatter=format_target_value,
        include_other=False,
        extra_rows_by_section=extra_rows,
    )
    for section in sections:
        title = section.get("title")
        if title == "Graphitisation":
            for row in section.get("rows", []):
                key = row.get("key")
                if key == "reactor_nr":
                    row["divider_before"] = True
                elif key == "graphitized":
                    row["divider_before"] = True
        elif title == "Results":
            for row in section.get("rows", []):
                if row.get("key") == "fm":
                    row["divider_before"] = True
    return sections

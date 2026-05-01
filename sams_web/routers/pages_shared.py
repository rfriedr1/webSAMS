"""Shared constants, helpers, and template wiring for page routers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from fastapi.templating import Jinja2Templates

from sams_web.config import get_settings
from sams_web.magic_nav import (
    MAGIC_IDENTIFIER_COMMAND_LABELS,
    MAGIC_IDENTIFIER_COMMAND_ROUTES,
    MAGIC_IDENTIFIER_PREFIX_LABELS,
    MAGIC_IDENTIFIER_PREFIX_ROUTES,
    MAGIC_IDENTIFIER_PREPARATION_LABEL,
    MAGIC_IDENTIFIER_SAMPLE_LABEL,
    MAGIC_IDENTIFIER_TARGET_LABEL,
    append_magic_feedback,
    build_magic_nav_rules,
    resolve_magic_identifier,
)
from sams_web.navigation import (
    MAIN_NAV_ITEMS,
    NAVIGATION_COMMAND_ENTRIES,
    SUB_NAV_ITEMS,
    is_subnav_active,
    resolve_active_module,
)
from sams_web.services import SamsService
from sams_web.thresholds import STANDARD_LABELS
from sams_web.viewmodels import detail_sections as ds

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

logger = logging.getLogger(__name__)
APP_SUBTITLE_BASE = "CEZA C14 Laboratory Information System"

LAST_SAMPLE_COOKIE = "last_sample_nr"

LAB_OPERATION_CONFIGS: dict[str, dict[str, Any]] = {
    "preparation": {
        "title": "Preparation Workflow",
        "description": "Preparation-centric view for chemistry and pre-treatment tracking.",
        "context": "preparations",
        "default_limit": 400,
        "columns": (
            "sample_nr",
            "prep_nr",
            "batch",
            "prep_start",
            "prep_end",
            "cn_ratio",
            "c_percent",
            "n_percent",
            "prep_comment",
        ),
    },
    "graphitization": {
        "title": "Graphitization Workflow",
        "description": "Target-centric view for graphitization, magazine assignment, and target handling.",
        "context": "targets",
        "default_limit": 400,
        "columns": (
            "sample_nr",
            "prep_nr",
            "target_nr",
            "graph_batch",
            "graphitized",
            "magazine",
            "position",
            "weight",
            "conc_c",
            "conc_n",
            "target_comment",
        ),
    },
    "analysis": {
        "title": "Analysis Workflow",
        "description": "Measurement-focused view with FM, d13C, and C14 result indicators.",
        "context": "targets",
        "default_limit": 400,
        "columns": (
            "sample_nr",
            "prep_nr",
            "target_nr",
            "magazine",
            "position",
            "calcset",
            "fm",
            "fm_sig",
            "dc13",
            "dc13_sig",
            "c14_age",
            "c14_age_sig",
            "meas_comment",
        ),
        "require_any_fields": ("c14_age", "fm", "dc13"),
    },
}

TABLE_HEADER_LABELS: dict[str, str] = {
    # Identifiers
    "sample_nr": "Sample #",
    "project_nr": "Project #",
    "user_nr": "Submitter #",
    "prep_nr": "Prep #",
    "target_nr": "Target #",
    "ma_nr": "MA #",
    "invoice_nr": "Invoice #",
    "auftragsnr": "Order ID",
    "order_nr": "Order #",
    "target_id": "Target ID",
    # Submitter
    "last_name": "Last Name",
    "first_name": "First Name",
    "user_last_name": "Submitter Last Name",
    "organisation": "Organisation",
    "institute": "Institute",
    "address_1": "Address 1",
    "address_2": "Address 2",
    "town": "Town",
    "country": "Country",
    "postcode": "Postcode",
    "phone_1": "Phone 1",
    "phone_2": "Phone 2",
    "email": "Email",
    "account": "Account",
    "user_comment": "Submitter Comment",
    # Project
    "project": "Project Name",
    "in_date": "In Date",
    "out_date": "Out Date",
    "desired_date": "Desired Date",
    "invoice_date": "Invoice Date",
    "invoice": "Invoice",
    "letter": "Letter",
    "project_comment": "Project Comment",
    "report": "Report",
    "report_type": "Report Type",
    "research": "Research",
    "advisor": "Advisor",
    "supervisor": "Supervisor",
    "priority": "Priority",
    "status": "Status",
    "project_type": "Project Type",
    "price": "Price",
    "free_of_charge": "Free of Charge",
    "sample_storage_loc": "Sample Storage Location",
    "return_to_sender": "Return to Sender",
    "returned_to_sender": "Returned to Sender",
    "prep_return_to_sender": "Prep Return to Sender",
    "prep_returned_to_sender": "Prep Returned to Sender",
    # Sample
    "type": "Type",
    "material": "Material",
    "fraction": "Fraction",
    "weight": "Weight",
    "sampling_date": "Sampling Date",
    "user_label": "Sample Label",
    "user_label_nr": "Sample Label #",
    "user_desc1": "Description 1",
    "user_desc2": "Description 2",
    "pre_sub_treat": "Submitter Pre-treatment",
    "preparation": "Preparation",
    "residue": "Residue",
    "lab_comment": "Lab Comment",
    "prep_storage_loc": "Prep Storage Location",
    "storage": "Storage",
    "photo": "Photo",
    # Sample / Target measurements
    "c14_age": "C14 Age",
    "c14_age_sig": "C14 Sigma",
    "fm": "FM",
    "fm_sig": "FM Sigma",
    "av_fm": "Average FM",
    "av_fm_sig": "Average FM Sigma",
    "av_dc13": "Average δ¹³C",
    "av_dc13_sig": "Average δ¹³C Sigma",
    "dc13": "δ¹³C",
    "dc13_sig": "δ¹³C Sigma",
    "delta_r": "Delta R",
    "calib": "Calibration",
    "cal1s_min": "Cal 1σ Min",
    "cal1s_max": "Cal 1σ Max",
    "cal2s_min": "Cal 2σ Min",
    "cal2s_max": "Cal 2σ Max",
    # Preparation
    "batch": "Prep Batch",
    "cn_ratio": "C/N Ratio",
    "cn_ratio_calc": "C/N Ratio",
    "c_percent": "C (%)",
    "n_percent": "N (%)",
    "prep_start": "Prep Start",
    "prep_end": "Prep End",
    "prep_comment": "Prep Comment",
    "weight_start": "Weight Start",
    "weight_medium": "Weight Mid",
    "weight_medium_2": "Weight Mid 2",
    "weight_end": "Weight End",
    # Target
    "magazine": "Magazine",
    "position": "Position",
    "graph_batch": "Graph Batch",
    "graphitized": "Graphitized",
    "target_pressed": "Target Pressed",
    "target_comment": "Target Comment",
    "meas_comment": "Measurement Comment",
    "weight_combustion": "Combustion Weight",
    "conc_c": "C (%)",
    "conc_n": "N (%)",
    "le_curr": "LE Current",
    "he_curr": "HE Current",
}


def format_table_header_label(key: Any) -> str:
    key_str = str(key)
    label = TABLE_HEADER_LABELS.get(key_str.lower())
    if label is not None:
        return label
    # Default: snake_case → Title Case for unknown columns
    return key_str.replace("_", " ").title()


def format_table_cell_value(key: Any, value: Any) -> Any:
    """Format a table cell's value for display.

    Returns "" for empty, sentinel-string ("undefined" / "null" / "n/a"),
    and sentinel dates (year < 1950). Numeric/date columns get type-specific
    formatting.
    """
    if ds.is_empty_display_value(value):
        return ""

    key_lower = str(key).lower()
    if "dc13" in key_lower or "d13c" in key_lower:
        formatted = ds.format_d13c(value)
        return "" if formatted is None else formatted
    if key_lower in {"c14_age", "c14_age_sig"}:
        formatted = ds.format_c14_integer(value)
        return "" if formatted is None else formatted
    if key_lower in {"conc_c", "conc_n"}:
        formatted = ds.format_one_decimal(value)
        return "" if formatted is None else formatted
    if key_lower in {"cn_ratio", "cn_ratio_calc"}:
        formatted = ds.format_cn_ratio(value)
        return "" if formatted is None else formatted
    return value


templates.env.globals["magic_identifier_prefix_labels"] = MAGIC_IDENTIFIER_PREFIX_LABELS
templates.env.globals["magic_identifier_sample_label"] = MAGIC_IDENTIFIER_SAMPLE_LABEL
templates.env.globals["magic_identifier_preparation_label"] = MAGIC_IDENTIFIER_PREPARATION_LABEL
templates.env.globals["magic_identifier_target_label"] = MAGIC_IDENTIFIER_TARGET_LABEL
templates.env.globals["magic_identifier_command_labels"] = MAGIC_IDENTIFIER_COMMAND_LABELS
templates.env.globals["format_c14_integer"] = ds.format_c14_integer
templates.env.globals["format_d13c"] = ds.format_d13c
templates.env.globals["format_one_decimal"] = ds.format_one_decimal
templates.env.globals["format_cn_ratio"] = ds.format_cn_ratio
templates.env.globals["format_cn_ratio_from_conc"] = ds.format_cn_ratio_from_conc
templates.env.globals["format_table_header_label"] = format_table_header_label
templates.env.globals["format_table_cell_value"] = format_table_cell_value
templates.env.globals["main_navigation_items"] = MAIN_NAV_ITEMS
templates.env.globals["sub_navigation_items"] = SUB_NAV_ITEMS
templates.env.globals["navigation_command_entries"] = NAVIGATION_COMMAND_ENTRIES
templates.env.globals["resolve_active_module"] = resolve_active_module
templates.env.globals["is_subnav_active"] = is_subnav_active
templates.env.globals["app_subtitle"] = f"{APP_SUBTITLE_BASE} ({get_settings().database_name})"


def build_threshold_rows(payload: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, key in STANDARD_LABELS:
        values = payload.get(key, {})
        rows.append(
            {
                "label": label,
                "key": key,
                "red_below": values.get("red_below", ""),
                "yellow_min": values.get("yellow_min", ""),
                "yellow_max": values.get("yellow_max", ""),
                "green_above": values.get("green_above", ""),
            }
        )
    return rows


def has_non_empty_value(row: dict[str, Any], keys: tuple[str, ...]) -> bool:
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip() == "":
            continue
        return True
    return False


def select_columns(rows: list[dict[str, Any]], preferred_columns: tuple[str, ...]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    available = {key for row in rows for key in row.keys()}
    selected = [key for key in preferred_columns if key in available]
    if not selected:
        return rows
    return [{key: row.get(key) for key in selected} for row in rows]


def render_lab_operation_page(
    request: Request,
    mode: str,
    phrase: str,
    limit: int,
    service: SamsService,
):
    config = LAB_OPERATION_CONFIGS[mode]
    context = config["context"]
    normalized_phrase = phrase.strip()
    resolved_limit = limit if limit > 0 else int(config["default_limit"])
    error: str | None = None
    rows: list[dict[str, Any]] = []
    try:
        rows = service.search(context=context, phrase=normalized_phrase, limit=resolved_limit)
        required_fields = config.get("require_any_fields")
        if required_fields:
            rows = [row for row in rows if has_non_empty_value(row, tuple(required_fields))]
        rows = select_columns(rows, tuple(config.get("columns", ())))
    except ValueError as exc:
        error = str(exc)

    return templates.TemplateResponse(
        "lab_operations.html",
        {
            "request": request,
            "mode": mode,
            "title": config["title"],
            "description": config["description"],
            "phrase": phrase,
            "limit": resolved_limit,
            "rows": rows,
            "error": error,
        },
    )


def parse_positive_int(raw_value: str) -> int | None:
    value = raw_value.strip()
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def resolve_jump_redirect_url(
    *,
    jump_value: str,
    current_id: int,
    max_id: int,
    fallback_url: str,
    target_url_for: Callable[[int], str],
    exists_fn: Callable[[int], bool],
) -> str | None:
    jump_id = parse_positive_int(jump_value)
    if jump_id is None:
        return fallback_url
    if max_id > 0 and jump_id > max_id:
        return fallback_url
    if jump_id == current_id:
        return None
    if exists_fn(jump_id):
        return target_url_for(jump_id)
    return fallback_url

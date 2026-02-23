"""Shared constants, helpers, and template wiring for page routers."""

from __future__ import annotations

import logging
from pathlib import Path
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import Request
from fastapi.templating import Jinja2Templates

from sams_web.config import get_settings
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

MAGIC_IDENTIFIER_PREFIX_ROUTES: dict[str, tuple[str, str]] = {
    "pr": ("project", "/projects/{identifier}"),
    "usr": ("user", "/users/{identifier}"),
}
MAGIC_IDENTIFIER_PREFIX_LABELS: dict[str, str] = {
    "pr": "project number",
    "usr": "user number",
}
MAGIC_IDENTIFIER_SAMPLE_LABEL = "sample number"
MAGIC_IDENTIFIER_COMMAND_ROUTES: dict[str, str] = {
    "/prep": "/lab/preparation",
    "/graph": "/lab/graphitization",
    "/ana": "/lab/analysis",
}
MAGIC_IDENTIFIER_COMMAND_LABELS: dict[str, str] = {
    "/prep": "magic command: preparation",
    "/graph": "magic command: graphitization",
    "/ana": "magic command: analysis",
}
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
    "conc_c": "C (%)",
    "conc_n": "N (%)",
    "cn_ratio": "C/N Ratio",
    "cn_ratio_calc": "C/N Ratio",
    "user_last_name": "User Last Name",
}


def format_table_header_label(key: Any) -> str:
    key_str = str(key)
    return TABLE_HEADER_LABELS.get(key_str.lower(), key_str)


def format_table_cell_value(key: Any, value: Any) -> Any:
    if value is None:
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


@dataclass(frozen=True)
class MagicNavResolution:
    """Typed representation of a resolved Magic Nav input."""

    kind: Literal["sample", "project", "user", "command"]
    target: str
    identifier: int | None = None


def resolve_magic_identifier(raw: str) -> MagicNavResolution | None:
    value = raw.strip().lower()
    if value == "":
        return None

    command_target = MAGIC_IDENTIFIER_COMMAND_ROUTES.get(value)
    if command_target is not None:
        return MagicNavResolution(kind="command", target=command_target)

    if re.fullmatch(r"\d+", value):
        identifier = int(value)
        return MagicNavResolution(kind="sample", identifier=identifier, target=f"/samples/{identifier}")

    prefixed = re.fullmatch(r"([a-z]+)[\s:_-]*(\d+)", value)
    if prefixed is None:
        return None

    prefix, identifier = prefixed.groups()
    route_spec = MAGIC_IDENTIFIER_PREFIX_ROUTES.get(prefix)
    if route_spec is None:
        return None
    entity_kind, target_template = route_spec
    numeric_id = int(identifier)
    return MagicNavResolution(
        kind=entity_kind,
        identifier=numeric_id,
        target=target_template.format(identifier=numeric_id),
    )


def append_magic_feedback(url: str, entered_value: str, error_message: str) -> str:
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["magic_identifier"] = entered_value
    query["magic_error"] = error_message
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def build_magic_nav_rules() -> list[dict[str, str]]:
    rules: list[dict[str, str]] = [
        {
            "pattern": "digits only",
            "example": "123",
            "description": f"Opens sample detail (label: {MAGIC_IDENTIFIER_SAMPLE_LABEL}).",
        }
    ]
    for prefix in sorted(MAGIC_IDENTIFIER_PREFIX_LABELS.keys()):
        route_spec = MAGIC_IDENTIFIER_PREFIX_ROUTES.get(prefix)
        if route_spec is None:
            continue
        entity_kind, _target_template = route_spec
        rules.append(
            {
                "pattern": f"{prefix}<number>",
                "example": f"{prefix}123",
                "description": (
                    f"Opens {entity_kind} detail "
                    f"(label: {MAGIC_IDENTIFIER_PREFIX_LABELS.get(prefix, 'unknown ID')})."
                ),
            }
        )
    for command in sorted(MAGIC_IDENTIFIER_COMMAND_ROUTES.keys()):
        command_target = MAGIC_IDENTIFIER_COMMAND_ROUTES[command]
        label = MAGIC_IDENTIFIER_COMMAND_LABELS.get(command, "magic command")
        rules.append(
            {
                "pattern": command,
                "example": command,
                "description": f"Runs {label} and opens {command_target}.",
            }
        )
    return rules


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

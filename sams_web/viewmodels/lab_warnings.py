"""Pure functions that evaluate lab-warning thresholds against an entity.

Each `evaluate_*_warnings` function returns a `dict[str, WarningOutcome]`
keyed by the threshold key (e.g. `"target_total_c_ug_min"`). Templates
read it as `{name}_warnings.get('target_total_c_ug_min')` and pass the
outcome straight to `render_detail_display_card(..., warning=...)`,
which paints the card red and shows the inline message when triggered.

Keeping this layer pure (no DB, no service, no request) makes warnings
easy to unit-test and easy to extend — adding a new threshold is a
new evaluator function plus a one-line entry in
`LAB_WARNING_THRESHOLD_FIELDS`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sams_web.lab_warning_thresholds import LAB_WARNING_THRESHOLD_FIELD_BY_KEY
from sams_web.viewmodels.detail_sections_common import (
    calculate_preparation_yield_value,
    format_total_c_ug,
)


@dataclass(frozen=True)
class WarningOutcome:
    """Single threshold evaluation result.

    `triggered` is what the template branches on. `threshold` and
    `actual` are kept around so the message can mention the configured
    bound, and so future tooling (e.g. an audit log) can inspect the
    numbers without re-evaluating.

    `field_key` is the section-grid row key the warning attaches to —
    e.g. `"total_c_ug"`. Used by `build_detail_page_context` to derive
    a `{name}_warnings_by_field` lookup so the section-grid macro can
    show the same red/⚠ treatment the headline card uses, instead of
    the warning living only on the headline.
    """

    triggered: bool
    threshold: float
    actual: float | None
    message: str
    field_key: str = ""


def _below_minimum_outcome(
    *,
    threshold_key: str,
    actual: float | None,
    thresholds: dict[str, Any],
    field_key: str = "",
) -> WarningOutcome | None:
    """Generic 'value-below-minimum' check. Returns None if the
    threshold is not configured (so callers can omit the entry from
    their result dict and templates simply don't render the warning)."""
    if threshold_key not in thresholds:
        return None
    field = LAB_WARNING_THRESHOLD_FIELD_BY_KEY.get(threshold_key)
    if field is None:
        return None
    try:
        threshold_value = float(thresholds[threshold_key])
    except (TypeError, ValueError):
        return None
    formatted_threshold = field.format(threshold_value)
    triggered = actual is not None and actual < threshold_value
    return WarningOutcome(
        triggered=triggered,
        threshold=threshold_value,
        actual=actual,
        message=f"Below {formatted_threshold} {field.unit} minimum",
        field_key=field_key,
    )


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_target_warnings(target: Any, thresholds: dict[str, Any]) -> dict[str, WarningOutcome]:
    total_c_ug = format_total_c_ug(target.weight_combustion, target.conc_c)
    outcome = _below_minimum_outcome(
        threshold_key="target_total_c_ug_min",
        actual=_coerce_float(total_c_ug),
        thresholds=thresholds,
        field_key="total_c_ug",
    )
    return {"target_total_c_ug_min": outcome} if outcome else {}


def evaluate_preparation_warnings(
    preparation: Any, thresholds: dict[str, Any]
) -> dict[str, WarningOutcome]:
    yield_percent = calculate_preparation_yield_value(
        preparation.weight_start, preparation.weight_end
    )
    outcome = _below_minimum_outcome(
        threshold_key="preparation_yield_percent_min",
        actual=yield_percent,
        thresholds=thresholds,
        field_key="yield_percent",
    )
    return {"preparation_yield_percent_min": outcome} if outcome else {}

"""Common detail-section helpers and formatting."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Iterable

from sqlalchemy.inspection import inspect

SectionSpec = tuple[str, str, tuple[str, ...]]
Row = dict[str, Any]
RowsBySectionFactory = Callable[[str], Iterable[Row]]


# ---- Empty-value detection -----------------------------------------------

# Sentinel-date threshold: legacy null-equivalents (1899-12-30, 1900-01-01,
# 0001-01-01 etc.) all fall well before this cutoff. Real radiocarbon
# laboratory work doesn't produce dates before 1950 in administrative
# fields like in_date / desired_date / out_date.
SENTINEL_DATE_CUTOFF = date(1950, 1, 1)

# Literal strings the legacy data set uses to mean "no value." Matched
# case-insensitively after stripping.
SENTINEL_STRING_TOKENS = frozenset({"undefined", "null", "n/a", "none", "-"})


def is_sentinel_date(value: Any) -> bool:
    """Return True if `value` is a date or datetime older than the
    sentinel-date cutoff (i.e. a legacy stand-in for null)."""
    if isinstance(value, datetime):
        value = value.date()
    if not isinstance(value, date):
        return False
    return value < SENTINEL_DATE_CUTOFF


def is_empty_display_value(value: Any) -> bool:
    """Return True if `value` should be rendered as "no data" (— in the UI).

    Empty: None, empty / whitespace-only string, sentinel string token
    ("undefined", "null", "n/a"), or a sentinel date.
    """
    if value is None:
        return True
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned == "":
            return True
        if cleaned in SENTINEL_STRING_TOKENS:
            return True
        return False
    if isinstance(value, (date, datetime)):
        return is_sentinel_date(value)
    return False


def display_value(value: Any) -> Any:
    """Pass-through for non-empty values; returns None for anything
    `is_empty_display_value` flags. Templates render `None` as "—" via
    the `detail-empty` span / `display(...)` macro."""
    if is_empty_display_value(value):
        return None
    return value


def mapped_values(entity: Any) -> dict[str, Any]:
    mapper = inspect(entity).mapper
    return {attr.key: getattr(entity, attr.key) for attr in mapper.column_attrs}


def default_label(key: str) -> str:
    return key.replace("_", " ").title()


def build_sections(
    entity: Any,
    *,
    field_labels: dict[str, str],
    section_specs: tuple[SectionSpec, ...],
    kind_resolver: Callable[[str], str],
    value_formatter: Callable[[str, Any], Any],
    include_other: bool = True,
    other_title: str = "Other",
    other_description: str = "Additional fields available in this record.",
    other_excluded_keys: set[str] | None = None,
    extra_rows_by_section: RowsBySectionFactory | None = None,
    drop_all_empty_sections: bool = False,
) -> list[dict[str, Any]]:
    """Build the section list. If `drop_all_empty_sections` is True,
    sections whose every row has an empty display value are omitted —
    useful for early-stage records (just-created samples / projects)
    where many groups would otherwise show all "—".
    """
    values_by_key = mapped_values(entity)
    sections: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    excluded_keys = other_excluded_keys or set()

    for title, description, keys in section_specs:
        rows: list[Row] = []
        for key in keys:
            if key not in values_by_key:
                continue
            seen_keys.add(key)
            rows.append(
                {
                    "key": key,
                    "label": field_labels.get(key, default_label(key)),
                    "kind": kind_resolver(key),
                    "raw_value": values_by_key[key],
                    "value": value_formatter(key, values_by_key[key]),
                }
            )

        if extra_rows_by_section:
            rows.extend(extra_rows_by_section(title))

        if rows:
            section_is_empty = all(is_empty_display_value(row.get("value")) for row in rows)
            if drop_all_empty_sections and section_is_empty:
                continue
            sections.append({
                "title": title,
                "description": description,
                "rows": rows,
                "is_empty": section_is_empty,
            })

    if include_other:
        other_rows = [
            {
                "key": key,
                "label": field_labels.get(key, default_label(key)),
                "kind": kind_resolver(key),
                "raw_value": values_by_key[key],
                "value": value_formatter(key, values_by_key[key]),
            }
            for key in sorted(values_by_key.keys())
            if key not in seen_keys and key not in excluded_keys
        ]
        if other_rows:
            sections.append(
                {
                    "title": other_title,
                    "description": other_description,
                    "rows": other_rows,
                }
            )

    return sections


def format_c14_integer(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return int(rounded)


def format_d13c(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return format(rounded, "f")


def format_one_decimal(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return format(rounded, "f")


def format_cn_ratio(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return format(rounded, "f")


def format_cn_ratio_from_conc(conc_c: Any, conc_n: Any) -> str | None:
    if conc_c is None or conc_n is None:
        return None
    try:
        c = Decimal(str(conc_c))
        n = Decimal(str(conc_n))
    except (InvalidOperation, ValueError):
        return None
    if n == 0:
        return None
    ratio = (c / Decimal("12.011")) / (n / Decimal("14.007"))
    return str(format_cn_ratio(ratio))

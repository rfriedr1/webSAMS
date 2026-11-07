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


def arrange_sections(
    sections: list[dict[str, Any]],
    *,
    order: tuple[str, ...] = (),
    wide: frozenset[str] | set[str] = frozenset(),
    more: frozenset[str] | set[str] = frozenset(),
) -> list[dict[str, Any]]:
    """Attach the fact-sheet layout hints the detail templates render by.

    Every section gets `layout` ("column" — one column of the fact sheet —
    or "wide", a full-width band such as Comments) and `placement`
    ("primary", shown on the page, or "more", folded into the collapsed
    additional-details block). Sections named in `order` come first, in
    that order; the rest keep their build order behind them.
    """
    rank = {title: index for index, title in enumerate(order)}
    for section in sections:
        title = section.get("title", "")
        section["layout"] = "wide" if title in wide else "column"
        section["placement"] = "more" if title in more else "primary"
    return sorted(
        sections,
        key=lambda section: rank.get(section.get("title", ""), len(rank)),
    )


def attach_readout(
    sections: list[dict[str, Any]],
    *,
    section_title: str,
    value_key: str,
    sigma_key: str,
    label: str,
    unit: str = "BP",
) -> None:
    """Lift a value ± sigma pair out of a section's rows into a readout.

    A radiocarbon age is read and quoted as one figure (`5923 ± 25 BP`),
    so the fact sheet shows it that way instead of as two rows. Only for
    read-only result pairs: the rows are removed, so nothing that could be
    edited may go through here.
    """
    for section in sections:
        if section.get("title") != section_title:
            continue
        rows = section.get("rows", [])
        by_key = {row.get("key"): row for row in rows}
        if value_key not in by_key:
            return
        section["readout"] = {
            "label": label,
            "unit": unit,
            "value": by_key[value_key].get("value"),
            "sigma": by_key.get(sigma_key, {}).get("value"),
        }
        section["rows"] = [row for row in rows if row.get("key") not in {value_key, sigma_key}]
        return


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


def calculate_preparation_yield_value(weight_start: Any, weight_end: Any) -> float | None:
    """Numeric yield (%) for warning evaluation. The display-formatted
    sibling lives in `detail_sections_sample_lab.calculate_preparation_yield`
    and rounds to 2 decimals; this version stays unrounded so threshold
    comparisons aren't biased by display rounding."""
    if weight_start is None or weight_end is None:
        return None
    try:
        start = Decimal(str(weight_start))
        end = Decimal(str(weight_end))
    except (InvalidOperation, ValueError):
        return None
    if start == 0:
        return None
    return float((end / start) * Decimal("100"))


def format_total_c_ug(weight_combustion: Any, conc_c: Any) -> str | None:
    """Total carbon mass in µg, from combustion weight (mg) and C concentration (%).

    µg C = weight_combustion_mg × (conc_c / 100) × 1000 = weight_combustion × conc_c × 10
    """
    if weight_combustion is None or conc_c is None:
        return None
    try:
        weight = Decimal(str(weight_combustion))
        c = Decimal(str(conc_c))
    except (InvalidOperation, ValueError):
        return None
    total_ug = weight * c * Decimal("10")
    rounded = total_ug.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return str(int(rounded))

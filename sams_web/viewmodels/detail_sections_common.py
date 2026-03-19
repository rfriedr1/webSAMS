"""Common detail-section helpers and formatting."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Iterable

from sqlalchemy.inspection import inspect

SectionSpec = tuple[str, str, tuple[str, ...]]
Row = dict[str, Any]
RowsBySectionFactory = Callable[[str], Iterable[Row]]


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
) -> list[dict[str, Any]]:
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
            sections.append({"title": title, "description": description, "rows": rows})

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

"""The importable-field registry: built-in fields plus operator-defined ones.

Why this exists
---------------
The set of columns the importer understands used to be a frozen constant.
That made every new customer column a code change. This module turns the
registry into data: a *built-in* core (the fields the standard template
carries) merged with *custom* fields an operator defines in
Setup → Import Column Headings.

A custom field is just three things:

    target column  — which `sample_t` column the value is written to
    label          — what the review UI calls it
    headings       — the spreadsheet headings that map to it

Because the target must be a real, writable `sample_t` column, a custom
field can never invent a place to store data — the DB schema stays the
boundary. `SAMPLE_TARGET_COLUMNS` derives that allow-list straight from
the ORM model, so adding a column to `models.Sample` automatically makes
it available here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import Date, DateTime, Float, Integer
from sqlalchemy.inspection import inspect as sa_inspect

from sams_web.models import Sample
from sams_web.sample_import.vocabulary import (
    SAMPLE_COLUMN_SYNONYMS,
    SAMPLE_FIELD_LABELS,
    merge_synonyms,
    normalize_label,
)

#: Columns an import must never write, whatever Setup says.
#:
#: - identity/FK columns are assigned by the commit step
#: - the BATS-owned result columns are populated by the measurement
#:   system (ADR-0003); letting a submission sheet set an age would be a
#:   data-integrity hole
#: - `editable` / `not_tobedated` are workflow flags set at intake
BLOCKED_TARGET_COLUMNS: frozenset[str] = frozenset(
    {
        "sample_nr",
        "project_nr",
        "editable",
        "not_tobedated",
        # BATS-owned / derived results
        "c14_age",
        "c14_age_sig",
        "av_fm",
        "av_fm_sig",
        "av_dc13",
        "av_dc13_sig",
        "cal1s_min",
        "cal1s_max",
        "cal2s_min",
        "cal2s_max",
        "delta_r",
        "calib",
    }
)

#: Sample columns backed by a controlled vocabulary. Values for these are
#: validated against the lookup table on commit.
LOOKUP_BACKED_COLUMNS: dict[str, str] = {
    "material": "get_materials",
    "type": "get_sample_types",
    "fraction": "get_fractions",
}


def _kind_for(column: Any) -> str:
    """Coarse value kind used for parsing and for the review editor."""
    if isinstance(column.type, (Date, DateTime)):
        return "date"
    if isinstance(column.type, (Float, Integer)):
        return "number"
    return "text"


@dataclass(frozen=True)
class TargetColumn:
    """A `sample_t` column an import field may write to."""

    name: str
    label: str
    kind: str
    max_length: int | None
    is_lookup: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "kind": self.kind,
            "max_length": self.max_length,
            "is_lookup": self.is_lookup,
        }


def _build_target_columns() -> dict[str, TargetColumn]:
    columns: dict[str, TargetColumn] = {}
    for attr in sa_inspect(Sample).column_attrs:
        name = attr.key
        if name in BLOCKED_TARGET_COLUMNS:
            continue
        column = attr.columns[0]
        columns[name] = TargetColumn(
            name=name,
            label=SAMPLE_FIELD_LABELS.get(name, name.replace("_", " ").title()),
            kind=_kind_for(column),
            max_length=getattr(column.type, "length", None),
            is_lookup=name in LOOKUP_BACKED_COLUMNS,
        )
    return columns


#: Every `sample_t` column a custom import field may target.
SAMPLE_TARGET_COLUMNS: dict[str, TargetColumn] = _build_target_columns()


@dataclass(frozen=True)
class ImportField:
    """One field the importer can read from a submission sheet."""

    key: str                 #: canonical name used throughout the wizard
    target: str              #: `sample_t` column it is written to
    label: str
    kind: str                #: text | number | date
    headings: tuple[str, ...]
    builtin: bool
    is_lookup: bool
    max_length: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "target": self.target,
            "label": self.label,
            "kind": self.kind,
            "headings": list(self.headings),
            "builtin": self.builtin,
            "is_lookup": self.is_lookup,
        }


@dataclass
class FieldRegistry:
    """The resolved set of importable fields for one request."""

    fields: dict[str, ImportField]

    @property
    def synonyms(self) -> dict[str, tuple[str, ...]]:
        """Heading vocabulary for the parser's header detection."""
        return {key: f.headings for key, f in self.fields.items()}

    @property
    def labels(self) -> dict[str, str]:
        return {key: f.label for key, f in self.fields.items()}

    @property
    def importable(self) -> frozenset[str]:
        return frozenset(self.fields)

    @property
    def lookup_fields(self) -> dict[str, str]:
        """Importable field key -> repo getter, for lookup validation."""
        return {
            key: LOOKUP_BACKED_COLUMNS[f.target]
            for key, f in self.fields.items()
            if f.target in LOOKUP_BACKED_COLUMNS
        }

    def target_for(self, key: str) -> str | None:
        field = self.fields.get(key)
        return field.target if field else None

    def as_payload(self) -> list[dict[str, Any]]:
        return [f.as_dict() for f in self.fields.values()]


def build_registry(custom_fields: list[dict[str, Any]] | None = None,
                   extra_headings: dict[str, list[str]] | None = None) -> FieldRegistry:
    """Resolve built-ins + operator definitions into one registry.

    `extra_headings` adds spellings to existing fields.
    `custom_fields` adds whole new fields, each `{key?, target, label, headings}`.

    A custom entry whose `target` matches a built-in field simply
    contributes extra headings to it, so an operator cannot accidentally
    create two fields writing to the same column.
    """
    merged_synonyms = merge_synonyms(SAMPLE_COLUMN_SYNONYMS, extra_headings)

    fields: dict[str, ImportField] = {}
    for key, headings in merged_synonyms.items():
        target = SAMPLE_TARGET_COLUMNS.get(key)
        fields[key] = ImportField(
            key=key,
            target=key,
            label=SAMPLE_FIELD_LABELS.get(key, key.replace("_", " ").title()),
            kind=target.kind if target else "text",
            headings=tuple(headings),
            builtin=True,
            is_lookup=key in LOOKUP_BACKED_COLUMNS,
            max_length=target.max_length if target else None,
        )

    for entry in custom_fields or []:
        target_name = str(entry.get("target") or "").strip()
        target = SAMPLE_TARGET_COLUMNS.get(target_name)
        if target is None:
            # Unknown or blocked column — ignore rather than fail the
            # import; the Setup editor only offers valid ones.
            continue
        headings = [str(h).strip() for h in (entry.get("headings") or []) if str(h).strip()]
        if not headings:
            continue

        if target_name in fields:
            # Fold into the built-in field instead of creating a rival.
            existing = fields[target_name]
            seen = {normalize_label(h) for h in existing.headings}
            combined = list(existing.headings)
            for heading in headings:
                if normalize_label(heading) not in seen:
                    seen.add(normalize_label(heading))
                    combined.append(heading)
            fields[target_name] = ImportField(
                key=existing.key,
                target=existing.target,
                label=str(entry.get("label") or existing.label),
                kind=existing.kind,
                headings=tuple(combined),
                builtin=existing.builtin,
                is_lookup=existing.is_lookup,
                max_length=existing.max_length,
            )
            continue

        fields[target_name] = ImportField(
            key=target_name,
            target=target_name,
            label=str(entry.get("label") or target.label),
            kind=target.kind,
            headings=tuple(headings),
            builtin=False,
            is_lookup=target.is_lookup,
            max_length=target.max_length,
        )

    return FieldRegistry(fields=fields)


def available_targets(used: set[str] | None = None) -> list[dict[str, Any]]:
    """Target columns offered in the Setup editor's picker."""
    used = used or set()
    return [
        {**col.as_dict(), "in_use": name in used}
        for name, col in sorted(SAMPLE_TARGET_COLUMNS.items(), key=lambda kv: kv[1].label)
    ]


__all__ = [
    "BLOCKED_TARGET_COLUMNS",
    "LOOKUP_BACKED_COLUMNS",
    "SAMPLE_TARGET_COLUMNS",
    "FieldRegistry",
    "ImportField",
    "TargetColumn",
    "available_targets",
    "build_registry",
]

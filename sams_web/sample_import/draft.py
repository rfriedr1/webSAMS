"""Typed result objects produced by the parser and consumed by the UI.

Everything here is plain data: JSON-serialisable via `as_dict()` so the
review step can round-trip a draft through the browser, let the operator
correct it, and post it back to the commit endpoint.

Every parsed value carries the spreadsheet cell it came from
(`sources`), so the review UI can show provenance and an operator can
always trace a value back to the sheet.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Severity levels for parse-time findings.
SEVERITY_ERROR = "error"      # blocks import until fixed
SEVERITY_WARNING = "warning"  # importable, but worth a look
SEVERITY_INFO = "info"        # purely informational


@dataclass
class Issue:
    """One finding attached to the draft, a field, or a sample row."""

    severity: str
    message: str
    #: Dotted path of what the issue is about, e.g. "project.project",
    #: "submitter.email", "samples[3].material". Lets the UI highlight
    #: the exact control that needs attention.
    target: str = ""
    #: Spreadsheet cell address, when the issue traces to one.
    cell: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "message": self.message,
            "target": self.target,
            "cell": self.cell,
        }


@dataclass
class ContactDraft:
    """A submitter or invoice-recipient block parsed from the sheet."""

    #: canonical contact field -> trimmed string value
    values: dict[str, str] = field(default_factory=dict)
    #: canonical contact field -> originating cell address
    sources: dict[str, str] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        return not any(v for v in self.values.values())

    @property
    def display_name(self) -> str:
        first = self.values.get("first_name", "").strip()
        last = self.values.get("last_name", "").strip()
        if first and last:
            return f"{last}, {first}"
        return last or first or self.values.get("organisation", "") or "(unnamed)"

    def as_dict(self) -> dict[str, Any]:
        return {
            "values": dict(self.values),
            "sources": dict(self.sources),
            "display_name": self.display_name,
            "is_empty": self.is_empty,
        }


@dataclass
class ProjectDraft:
    """Project-level metadata parsed from the sheet."""

    values: dict[str, Any] = field(default_factory=dict)
    sources: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"values": dict(self.values), "sources": dict(self.sources)}


@dataclass
class ColumnMapping:
    """How one spreadsheet column in the sample table was interpreted.

    Surfaced in the review UI so the operator can re-map or ignore any
    column — this is what makes added/renamed columns non-breaking.
    """

    column: int                 #: 1-indexed spreadsheet column
    column_letter: str
    header_text: str            #: raw header cell text
    field_name: str | None      #: canonical sample field, or None if unmapped
    confidence: float           #: 0..1 from the label resolver

    def as_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "column_letter": self.column_letter,
            "header_text": self.header_text,
            "field": self.field_name,
            "confidence": self.confidence,
        }


@dataclass
class SampleDraft:
    """One prospective `sample_t` row."""

    #: spreadsheet row number this came from
    row_number: int
    #: canonical sample field -> value (str for text, float for weight)
    values: dict[str, Any] = field(default_factory=dict)
    #: values from columns that could not be mapped, kept so nothing is
    #: silently lost; the UI can show them and the operator can map them.
    extras: dict[str, str] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)
    #: operator can untick a row to leave it out of the import
    include: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "values": dict(self.values),
            "extras": dict(self.extras),
            "issues": [i.as_dict() for i in self.issues],
            "include": self.include,
        }


@dataclass
class ImportDraft:
    """The complete parse result handed to the review step."""

    sheet_name: str
    file_name: str
    submitter: ContactDraft = field(default_factory=ContactDraft)
    invoice: ContactDraft = field(default_factory=ContactDraft)
    #: True when the sheet says the submitter address is also the
    #: billing address (or no separate invoice block was filled in).
    same_invoice_address: bool = True
    project: ProjectDraft = field(default_factory=ProjectDraft)
    columns: list[ColumnMapping] = field(default_factory=list)
    samples: list[SampleDraft] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    #: row number of the detected sample-table header (0 if not found)
    header_row: int = 0

    @property
    def error_count(self) -> int:
        own = sum(1 for i in self.issues if i.severity == SEVERITY_ERROR)
        rows = sum(
            1
            for s in self.samples
            for i in s.issues
            if i.severity == SEVERITY_ERROR
        )
        return own + rows

    @property
    def mapped_fields(self) -> list[str]:
        return [c.field_name for c in self.columns if c.field_name]

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "file_name": self.file_name,
            "header_row": self.header_row,
            "submitter": self.submitter.as_dict(),
            "invoice": self.invoice.as_dict(),
            "same_invoice_address": self.same_invoice_address,
            "project": self.project.as_dict(),
            "columns": [c.as_dict() for c in self.columns],
            "samples": [s.as_dict() for s in self.samples],
            "issues": [i.as_dict() for i in self.issues],
            "error_count": self.error_count,
            "sample_count": len(self.samples),
        }


__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_INFO",
    "SEVERITY_WARNING",
    "ColumnMapping",
    "ContactDraft",
    "ImportDraft",
    "Issue",
    "ProjectDraft",
    "SampleDraft",
]

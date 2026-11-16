"""Record actions: named tasks on a record page that change many records.

A record action sets one field to one value on a set of records under the
page's record — e.g. *Set C/N Isotope Analysis* on the samples of a
project. Decisions: `docs/adr/0007-record-actions.md`.

- The **owner** is the page the action is run from (`project`,
  `submitter`). Its related table holds the **rows** the operator can tick
  (a project's samples, a submitter's projects). No ticks means all rows.
- The **child** is the kind of record the action writes. It is the row
  itself, or reached through it (the preparations of the ticked samples).
- Every action is previewed first (`plan`), then run (`apply`). Both go
  through `SamsService.apply_many_and_commit`, i.e. through
  `apply_detail_update`, so a record that its detail page would refuse to
  save (an old sample with no type, say) is listed as refused and left
  alone; the rest are written in one commit.

**To add an action:** for a flag, one `_FLAGS` entry; for a free-text
field the operator edits per record, one `_TEXT_FIELDS` entry (an *Edit*
action, whose dialog lists every record with its current value, plus a
*Clear*). Anything else gets its own subclass of `RecordAction` — e.g.
`ReturnedAction`, which writes the project of a project page itself and
refuses *Set* when no sample (or prep) has any leftover to return.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Callable

from sams_web.access import Permission
from sams_web.detail_update import DetailUpdateConfig
from sams_web.field_labels import field_label
from sams_web.viewmodels.detail_sections_sample_lab import PREPARATION_DETAIL, SAMPLE_DETAIL, TARGET_DETAIL
from sams_web.viewmodels.detail_sections_user_project import PROJECT_DETAIL

if TYPE_CHECKING:
    from sams_web.services import SamsService


PREVIEW_ROW_LIMIT = 200
"""The preview lists at most this many changes; the count is always exact."""


@dataclass(frozen=True)
class Kind:
    """One kind of record an action can reach."""

    key: str
    singular: str
    plural: str
    config: DetailUpdateConfig | None
    ref_field: str = ""
    """Field keys behind a `RecordRef`'s number and label: their labels head
    the columns of the editor's Excel download."""
    label_field: str = ""


KINDS: dict[str, Kind] = {
    "sample": Kind("sample", "sample", "samples", SAMPLE_DETAIL, "sample_nr", "user_label"),
    "preparation": Kind("preparation", "preparation", "preparations", PREPARATION_DETAIL, "prep_nr", "batch"),
    "target": Kind("target", "target", "targets", TARGET_DETAIL, "target_id", "graph_batch"),
    "project": Kind("project", "project", "projects", PROJECT_DETAIL, "project_nr", "project"),
    "submitter": Kind("submitter", "submitter", "submitters", None),
}

OWNER_ROW_KIND: dict[str, str] = {
    "project": "sample",
    "submitter": "project",
}
"""Which rows the owner page's related table lists (and the operator ticks)."""


def noun(kind: str, count: int) -> str:
    k = KINDS[kind]
    return k.singular if count == 1 else k.plural


# ---- Records ---------------------------------------------------------------


@dataclass(frozen=True)
class RecordRef:
    """A record as the preview shows it: number, link, a short label."""

    key: Any
    ref: str
    href: str
    label: str


def _ref_for(kind: str, record: Any) -> RecordRef:
    if kind == "sample":
        return RecordRef(
            key=record.sample_nr,
            ref=str(record.sample_nr),
            href=f"/samples/{record.sample_nr}",
            label=record.user_label or "",
        )
    if kind == "preparation":
        return RecordRef(
            key=(record.sample_nr, record.prep_nr),
            ref=f"{record.sample_nr} / {record.prep_nr}",
            href=f"/samples/{record.sample_nr}/preparations/{record.prep_nr}",
            label=record.batch or "",
        )
    if kind == "target":
        return RecordRef(
            key=(record.sample_nr, record.prep_nr, record.target_nr),
            ref=f"{record.sample_nr}.{record.prep_nr}.{record.target_nr}",
            href=f"/samples/{record.sample_nr}/preparations/{record.prep_nr}/targets/{record.target_nr}",
            label=record.graph_batch or "",
        )
    if kind == "project":
        return RecordRef(
            key=record.project_nr,
            ref=str(record.project_nr),
            href=f"/projects/{record.project_nr}",
            label=record.project or "",
        )
    raise ValueError(f"Unknown record kind: {kind}")


def _row_nr(row_kind: str, row: Any) -> int:
    return row.sample_nr if row_kind == "sample" else row.project_nr


def owner_exists(service: "SamsService", owner: str, owner_nr: int) -> bool:
    if owner == "project":
        return service.repo.get_project(owner_nr) is not None
    if owner == "submitter":
        return service.repo.get_submitter(owner_nr) is not None
    return False


def owner_rows(service: "SamsService", owner: str, owner_nr: int, selected: list[int]) -> list[Any]:
    """The rows an action runs on: the ticked ones, or all when none are.

    A ticked number that does not belong to the owner is refused rather
    than skipped: the form was tampered with or the page is stale.
    """
    repo = service.repo
    if owner == "project":
        rows = repo.list_samples_by_project(owner_nr)
    elif owner == "submitter":
        rows = repo.list_projects_by_submitter(owner_nr)
    else:
        raise ValueError(f"Unknown owner: {owner}")
    if not selected:
        return rows
    row_kind = OWNER_ROW_KIND[owner]
    by_nr = {_row_nr(row_kind, row): row for row in rows}
    stray = [nr for nr in selected if nr not in by_nr]
    if stray:
        raise ValueError(
            f"{KINDS[row_kind].singular.capitalize()} {stray[0]} is not in {owner} {owner_nr}. "
            "Reload the page and tick again."
        )
    wanted = set(selected)
    return [row for nr, row in by_nr.items() if nr in wanted]


def _reach(service: "SamsService", row_kind: str, rows: list[Any], child: str) -> list[Any]:
    """Records of kind `child` under (or equal to) the given rows."""
    repo = service.repo
    if child == row_kind:
        return list(rows)
    if row_kind == "sample" and child == "preparation":
        return repo.list_preparations_by_samples([row.sample_nr for row in rows])
    if row_kind == "sample" and child == "target":
        return repo.list_targets_by_samples([row.sample_nr for row in rows])
    raise ValueError(f"A {row_kind} row cannot reach {child} records.")


def _owner_record(service: "SamsService", owner: str, owner_nr: int) -> Any:
    if owner == "project":
        record = service.repo.get_project(owner_nr)
    else:
        raise ValueError(f"An action cannot write the {owner} itself.")
    if record is None:
        raise ValueError(f"{owner.capitalize()} {owner_nr} does not exist.")
    return record


# ---- Actions ---------------------------------------------------------------


@dataclass(frozen=True)
class RecordAction:
    """Set `field` to `value` on the `child` records under the ticked rows."""

    key: str
    child: str
    field: str
    value: Any
    verb: str
    owners: tuple[str, ...]
    permission: Permission = Permission.EDIT_RECORDS
    warn: Callable[[Any, "RecordAction"], str | None] | None = None
    value_kind: str = "flag"
    """`flag` (shown Yes / No) or `text` (shown as is)."""

    edits_values = False
    """True for an action whose new value is typed per record (`EditTextAction`)."""

    on_owner = False
    """True for an action that writes the owner record itself (the project
    of a project page): the ticks do not apply."""

    def scope_facts(self, service: "SamsService", rows: list[Any]) -> dict[str, Any] | None:
        """Extra facts for the preview (e.g. how many samples have no leftover)."""
        return None

    def refusal(self, record: Any, facts: dict[str, Any] | None) -> str | None:
        """Why this action may not change `record`, beyond its page's own checks."""
        return None

    @property
    def field_title(self) -> str:
        return field_label(self.field)

    @property
    def title(self) -> str:
        return f"{self.verb} {self.field_title} on {KINDS[self.child].plural}"

    def current_value(self, record: Any) -> Any:
        return getattr(record, self.field, None)

    def new_value(self, record: Any, values: dict[str, str] | None) -> Any:
        return self.value

    def is_unchanged(self, record: Any, new: Any) -> bool:
        current = self.current_value(record)
        if isinstance(current, str):
            current = current.strip() or None
        if new in (0, None, ""):
            # "Clear" means "not set": an empty legacy value already is.
            return not current
        return current == new

    def display(self, value: Any) -> str:
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return value.isoformat() if value.year >= 1950 else "—"
        if self.value_kind == "text":
            text = (value or "").strip() if isinstance(value, str) else value
            return str(text) if text else "—"
        return format_flag(value)

    def form_for(self, record: Any, new: Any) -> dict[str, str]:
        config = KINDS[self.child].config
        raw = "" if new is None else str(new)
        return {f"{config.prefix}{self.field}": raw}


@dataclass(frozen=True)
class EditTextAction(RecordAction):
    """Type a new value per record: the dialog lists every record with its
    current value filled in. `values` maps a record's ref to its new text;
    a record left out keeps its value."""

    edits_values = True
    input_type = "text"

    mark_suffix: str | None = None
    """A letter the dialog's *Add …* button appends to every value, e.g. `E`
    (*entnommen*) on a storage location: the sample was taken out. Only
    the browser applies it; the posted values are ordinary edits."""

    leftover_kind: str | None = None
    """`sample` or `preparation`: the dialog shows, per sample, whether that
    sample (or its preps) has no leftover — a storage location for nothing."""

    def row_note(self, record: Any) -> str | None:
        """A short chip beside a record in the editor (e.g. *Discarded*)."""
        return None

    def leftover_by_record(self, service: "SamsService", records: list[Any]) -> dict[Any, tuple[int, int]]:
        """Sample key → (records with no leftover, records), for `leftover_kind`."""
        if self.leftover_kind == "sample":
            return {r.sample_nr: (1 if r.s_no_leftover else 0, 1) for r in records}
        if self.leftover_kind == "preparation":
            counts: dict[Any, tuple[int, int]] = {r.sample_nr: (0, 0) for r in records}
            for prep in service.repo.list_preparations_by_samples([r.sample_nr for r in records]):
                none, total = counts.get(prep.sample_nr, (0, 0))
                counts[prep.sample_nr] = (none + (1 if prep.p_no_leftover else 0), total + 1)
            return counts
        return {}

    @property
    def max_length(self) -> int | None:
        column = KINDS[self.child].config.model.__table__.columns.get(self.field)
        return getattr(column.type, "length", None) if column is not None else None

    def new_value(self, record: Any, values: dict[str, str] | None) -> Any:
        ref = _ref_for(self.child, record).ref
        if not values or ref not in values:
            return self.current_value(record)
        text = (values[ref] or "").strip()
        limit = self.max_length
        if limit and len(text) > limit:
            raise ValueError(
                f"{self.field_title} of {KINDS[self.child].singular} {ref} is {len(text)} characters long; "
                f"at most {limit} fit."
            )
        return text or None


@dataclass(frozen=True)
class EditDateAction(EditTextAction):
    """Type a date per record (e.g. *Graphitized* on a project's targets).
    The dialog shows date boxes and offers today's date in *Fill all*. The
    value is posted as `YYYY-MM-DD`; a date-time column stores midnight,
    like the benches' own date stamps."""

    input_type = "date"

    def current_value(self, record: Any) -> Any:
        value = getattr(record, self.field, None)
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            # Legacy sentinel dates (1899-12-30) read as empty.
            return value.isoformat() if value.year >= 1950 else None
        return value

    @property
    def max_length(self) -> int | None:
        return None

    def new_value(self, record: Any, values: dict[str, str] | None) -> Any:
        ref = _ref_for(self.child, record).ref
        if not values or ref not in values:
            return self.current_value(record)
        text = (values[ref] or "").strip()
        if not text:
            return None
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            raise ValueError(
                f"{self.field_title} of {KINDS[self.child].singular} {ref}: '{text}' is not a date (YYYY-MM-DD)."
            ) from None
        if parsed.year < 1950:
            raise ValueError(f"{self.field_title} of {KINDS[self.child].singular} {ref}: {text} is too early.")
        return parsed.isoformat()

    def row_note(self, record: Any) -> str | None:
        return "Discarded" if getattr(record, "stop", None) else None


@dataclass(frozen=True)
class ReturnedAction(RecordAction):
    """*Set / Clear Returned to Sender* (or *Prep Returned …*) on the project
    of a project page. Samples or preparations with no leftover cannot be
    returned, so the preview counts them, and *Set* is refused when every
    one of them has no leftover (nothing was left to send back)."""

    on_owner = True
    leftover_kind: str = "sample"

    @property
    def title(self) -> str:
        return f"{self.verb} {self.field_title} on this {KINDS[self.child].singular}"
    """`sample` (`s_no_leftover`) or `preparation` (`p_no_leftover`)."""

    @property
    def leftover_field(self) -> str:
        return "s_no_leftover" if self.leftover_kind == "sample" else "p_no_leftover"

    def scope_facts(self, service: "SamsService", rows: list[Any]) -> dict[str, Any]:
        records = _reach(service, "sample", rows, self.leftover_kind)
        no_leftover = sum(1 for r in records if getattr(r, self.leftover_field, None))
        return {
            "leftover": {
                "total": len(records),
                "no_leftover": no_leftover,
                "returnable": len(records) - no_leftover,
                "noun": KINDS[self.leftover_kind].plural,
                "singular": KINDS[self.leftover_kind].singular,
            }
        }

    def refusal(self, record: Any, facts: dict[str, Any] | None) -> str | None:
        if not self.value or not facts:
            return None
        leftover = facts["leftover"]
        if leftover["total"] == 0:
            return f"The project has no {leftover['noun']}, so nothing can be returned."
        if leftover["returnable"] == 0:
            who = (
                f"The only {leftover['singular']} has"
                if leftover["total"] == 1
                else f"All {leftover['total']} {leftover['noun']} have"
            )
            return f"{who} no leftover, so nothing can be returned."
        return None


def _warn_return_not_requested(record: Any, action: RecordAction) -> str | None:
    requested_field = action.field.replace("returned_to_sender", "return_to_sender")
    if action.value and not getattr(record, requested_field, None):
        return (
            f"Project {record.project_nr} does not ask for this ({field_label(requested_field)} is not set)."
        )
    return None


def leftover_text(kind: str, no_leftover: int, total: int) -> str | None:
    """Per-sample note in the storage-location editor; None when there is leftover."""
    if not no_leftover:
        return None
    if kind == "sample":
        return "No leftover"
    if no_leftover == total:
        return "No leftover" if total == 1 else f"No leftover (all {total} preps)"
    return f"{no_leftover} of {total} preps no leftover"


def format_flag(value: Any) -> str:
    if value is None:
        return "—"
    return "Yes" if value else "No"


def _warn_cn_moved(record: Any, action: RecordAction) -> str | None:
    if action.value == 0 and getattr(record, "c_n_isotop_a_moved", None):
        return f"Sample {record.sample_nr} was already moved to C/N analysis."
    return None


def _flag_pair(child: str, field_name: str, owners: tuple[str, ...], warn=None) -> list[RecordAction]:
    return [
        RecordAction(
            key=f"{child}.{field_name}.{suffix}",
            child=child,
            field=field_name,
            value=value,
            verb=verb,
            owners=owners,
            warn=warn,
        )
        for suffix, verb, value in (("set", "Set", 1), ("clear", "Clear", 0))
    ]


_PROJECT = ("project",)
_SUBMITTER = ("submitter",)

_FLAGS: tuple[tuple[str, str, tuple[str, ...], Any], ...] = (
    # Sample and prep flags belong to the project page (removed from the
    # submitter page 2026-11: not needed there, the project is the place).
    ("sample", "c_n_isotop_a", _PROJECT, _warn_cn_moved),
    ("sample", "dendro_a", _PROJECT, None),
    ("sample", "s_no_leftover", _PROJECT, None),
    ("preparation", "p_no_leftover", _PROJECT, None),
    ("project", "return_to_sender", _SUBMITTER, None),
    ("project", "prep_return_to_sender", _SUBMITTER, None),
)

def _text_pair(
    child: str,
    field_name: str,
    owners: tuple[str, ...],
    mark_suffix: str | None = None,
    leftover_kind: str | None = None,
) -> list[RecordAction]:
    return [
        EditTextAction(
            key=f"{child}.{field_name}.edit", child=child, field=field_name, value=None,
            verb="Edit", owners=owners, value_kind="text", mark_suffix=mark_suffix,
            leftover_kind=leftover_kind,
        ),
        RecordAction(
            key=f"{child}.{field_name}.clear", child=child, field=field_name, value=None,
            verb="Clear", owners=owners, value_kind="text",
        ),
    ]


STORAGE_TAKEN_SUFFIX = "E"
"""Appended to a storage location when the sample was taken out (*entnommen*): `266` → `266E`."""

_TEXT_FIELDS: tuple[tuple[str, str, tuple[str, ...], str | None, str | None], ...] = (
    # child, field, owners, mark suffix (the dialog's "Add …" button),
    # whose No Leftover the dialog shows per record
    ("sample", "s_storage_loc", _PROJECT, STORAGE_TAKEN_SUFFIX, "sample"),
    ("sample", "prep_storage_loc", _PROJECT, STORAGE_TAKEN_SUFFIX, "preparation"),
)

_DATE_FIELDS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # child, field, owners — a date typed per record, Fill all offers today
    ("target", "graphitized", _PROJECT),
)


def _date_pair(child: str, field_name: str, owners: tuple[str, ...]) -> list[RecordAction]:
    return [
        EditDateAction(
            key=f"{child}.{field_name}.edit", child=child, field=field_name, value=None,
            verb="Edit", owners=owners, value_kind="text",
        ),
        RecordAction(
            key=f"{child}.{field_name}.clear", child=child, field=field_name, value=None,
            verb="Clear", owners=owners, value_kind="text",
        ),
    ]


_RETURNED_FLAGS: tuple[tuple[str, str], ...] = (
    # field on project_t, kind whose no-leftover flag decides what can go back
    ("returned_to_sender", "sample"),
    ("prep_returned_to_sender", "preparation"),
)


def _returned_pair(field_name: str, leftover_kind: str) -> list[RecordAction]:
    return [
        ReturnedAction(
            key=f"project.{field_name}.{suffix}", child="project", field=field_name, value=value,
            verb=verb, owners=_PROJECT, warn=_warn_return_not_requested, leftover_kind=leftover_kind,
        )
        for suffix, verb, value in (("set", "Set", 1), ("clear", "Clear", 0))
    ]


RECORD_ACTIONS: dict[str, RecordAction] = {
    action.key: action
    for action in (
        *(a for child, field_name, owners, warn in _FLAGS for a in _flag_pair(child, field_name, owners, warn)),
        *(
            a
            for child, field_name, owners, suffix, leftover in _TEXT_FIELDS
            for a in _text_pair(child, field_name, owners, suffix, leftover)
        ),
        *(a for child, field_name, owners in _DATE_FIELDS for a in _date_pair(child, field_name, owners)),
        # Last in the menu: they write the project itself, not the ticked rows.
        *(a for field_name, kind in _RETURNED_FLAGS for a in _returned_pair(field_name, kind)),
    )
}


def action_for(owner: str, key: str) -> RecordAction:
    """The action `key` offered on `owner` pages; `KeyError` otherwise."""
    action = RECORD_ACTIONS[key]
    if owner not in action.owners:
        raise KeyError(key)
    return action


def action_menu(owner: str) -> list[dict[str, Any]]:
    """The Actions menu for an owner page: grouped by the kind of record
    written, one row per field with its Set / Clear pair."""
    groups: dict[str, dict[str, Any]] = {}
    for action in RECORD_ACTIONS.values():
        if owner not in action.owners:
            continue
        title = f"This {KINDS[action.child].singular}" if action.on_owner else KINDS[action.child].plural.capitalize()
        group = groups.setdefault(
            action.child,
            {"kind": action.child, "title": title, "items": {}},
        )
        item = group["items"].setdefault(
            action.field, {"field": action.field, "label": action.field_title, "actions": []}
        )
        item["actions"].append({"key": action.key, "verb": action.verb, "title": action.title})
    return [{**g, "items": list(g["items"].values())} for g in groups.values()]


# ---- Plan and apply --------------------------------------------------------


@dataclass(frozen=True)
class PlannedChange:
    record: RecordRef
    old: str
    new: str


@dataclass(frozen=True)
class Refused:
    record: RecordRef
    reason: str


@dataclass(frozen=True)
class EditorRow:
    """One record in an Edit action's dialog: its current value, and why
    it cannot be changed when its detail page would refuse a save."""

    record: RecordRef
    value: str
    refused: str | None
    leftover: str | None = None
    """"No leftover" (or "1 of 2 preps no leftover") when that applies."""
    no_leftover: bool = False
    """True when nothing of this record is left (all of its preps, for preps)."""
    note: str | None = None
    """Any other chip for the row (`EditTextAction.row_note`), e.g. *Discarded*."""


@dataclass(frozen=True)
class ActionPlan:
    action: RecordAction
    row_kind: str
    row_count: int
    record_count: int
    changes: tuple[PlannedChange, ...]
    unchanged: int
    refused: tuple[Refused, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)
    editor: tuple[EditorRow, ...] = field(default_factory=tuple)
    facts: dict[str, Any] | None = None

    def as_json(self) -> dict[str, Any]:
        child = self.action.child
        payload = {
            "key": self.action.key,
            "mode": "edit" if self.action.edits_values else "fixed",
            "title": self.action.title,
            "verb": self.action.verb,
            "field": self.action.field_title,
            "child": {"singular": KINDS[child].singular, "plural": KINDS[child].plural},
            "rows": {"count": self.row_count, "noun": noun(self.row_kind, self.row_count)},
            "record_count": self.record_count,
            "change_count": len(self.changes),
            "unchanged": self.unchanged,
            "changes": [
                {"ref": c.record.ref, "href": c.record.href, "label": c.record.label, "old": c.old, "new": c.new}
                for c in self.changes[:PREVIEW_ROW_LIMIT]
            ],
            "refused": [
                {"ref": r.record.ref, "href": r.record.href, "label": r.record.label, "reason": r.reason}
                for r in self.refused[:PREVIEW_ROW_LIMIT]
            ],
            "refused_count": len(self.refused),
            "warnings": list(self.warnings),
            "on_owner": self.action.on_owner,
        }
        if self.facts:
            payload.update(self.facts)
        if self.action.edits_values:
            # The whole list: the operator edits every record, so no cap.
            payload["editor"] = {
                "max_length": self.action.max_length,
                "mark_suffix": self.action.mark_suffix,
                "input_type": self.action.input_type,
                "fill_default": date.today().isoformat() if self.action.input_type == "date" else None,
                "columns": [field_label(KINDS[child].ref_field), field_label(KINDS[child].label_field)],
                "rows": [
                    {
                        "ref": r.record.ref, "href": r.record.href, "label": r.record.label,
                        "value": r.value, "refused": r.refused,
                        "leftover": r.leftover, "no_leftover": r.no_leftover, "note": r.note,
                    }
                    for r in self.editor
                ],
            }
            kind = self.action.leftover_kind
            if kind:
                payload["editor"]["leftover"] = {
                    "kind": kind,
                    "column": "No Leftover" if kind == "sample" else "Prep No Leftover",
                    "count": sum(1 for r in self.editor if r.no_leftover),
                    "partly": sum(1 for r in self.editor if r.leftover and not r.no_leftover),
                    "total": len(self.editor),
                }
        return payload


@dataclass(frozen=True)
class ActionOutcome:
    action: RecordAction
    changed: int
    unchanged: int
    refused: tuple[Refused, ...]

    def notice(self) -> str:
        child = self.action.child
        verb_done = {"Set": "set", "Clear": "cleared", "Edit": "changed"}.get(self.action.verb, self.action.verb.lower())
        parts = [f"{self.action.field_title} {verb_done} on {self.changed} {noun(child, self.changed)}"]
        if self.unchanged and self.action.verb != "Edit":
            parts.append(f"{self.unchanged} already {verb_done}")
        if self.refused:
            first = self.refused[0]
            parts.append(
                f"{len(self.refused)} not changed ({KINDS[child].singular} {first.record.ref}: {first.reason})"
            )
        return " · ".join(parts) + "."


def _run(
    service: "SamsService",
    action: RecordAction,
    owner: str,
    owner_nr: int,
    selected: list[int],
    *,
    dry_run: bool,
    values: dict[str, str] | None = None,
) -> tuple[ActionPlan, list[Any]]:
    row_kind = OWNER_ROW_KIND[owner]
    if action.on_owner:
        # The owner record itself: ticks do not apply, every row counts.
        rows = owner_rows(service, owner, owner_nr, [])
        records = [_owner_record(service, owner, owner_nr)]
    else:
        rows = owner_rows(service, owner, owner_nr, selected)
        records = _reach(service, row_kind, rows, action.child)
    facts = action.scope_facts(service, rows)
    config = KINDS[action.child].config

    if values:
        in_scope = {_ref_for(action.child, record).ref for record in records}
        stray = [ref for ref in values if ref not in in_scope]
        if stray:
            raise ValueError(
                f"{KINDS[action.child].singular.capitalize()} {stray[0]} is not in this selection. "
                "Reload the page and try again."
            )

    candidates: list[tuple[Any, RecordRef, str, Any]] = []
    unchanged = 0
    warnings: list[str] = []
    blocked: list[Refused] = []
    for record in records:
        new = action.new_value(record, values)
        if action.is_unchanged(record, new):
            unchanged += 1
            continue
        reason = action.refusal(record, facts)
        if reason:
            blocked.append(Refused(_ref_for(action.child, record), reason))
            continue
        if action.warn is not None:
            message = action.warn(record, action)
            if message:
                warnings.append(message)
        candidates.append((record, _ref_for(action.child, record), action.display(action.current_value(record)), new))

    editor: tuple[EditorRow, ...] = ()
    if action.edits_values and values is None:
        # Opening the editor: probe every record with its own value, so a
        # record its detail page would refuse is marked before anyone types.
        probe = [
            (_ref_for(action.child, r).key, action.form_for(r, action.current_value(r))) for r in records
        ]
        refused_probe = dict(service.apply_many_and_commit(config, probe, dry_run=True)) if probe else {}
        leftover = action.leftover_by_record(service, records)
        rows_out = []
        for record in records:
            ref = _ref_for(action.child, record)
            none, total = leftover.get(ref.key, (0, 0))
            rows_out.append(EditorRow(
                ref,
                (action.current_value(record) or "").strip(),
                refused_probe.get(ref.key),
                leftover=leftover_text(action.leftover_kind, none, total) if action.leftover_kind else None,
                no_leftover=bool(total) and none == total,
                note=action.row_note(record),
            ))
        editor = tuple(rows_out)

    updates = [(ref.key, action.form_for(record, new)) for record, ref, _old, new in candidates]
    rejected = dict(service.apply_many_and_commit(config, updates, dry_run=dry_run)) if updates else {}

    changes = tuple(
        PlannedChange(ref, old, action.display(new))
        for _record, ref, old, new in candidates
        if ref.key not in rejected
    )
    refused = tuple(blocked) + tuple(
        Refused(ref, rejected[ref.key]) for _record, ref, _old, _new in candidates if ref.key in rejected
    )
    plan = ActionPlan(
        action=action,
        row_kind=row_kind,
        row_count=len(rows),
        record_count=len(records),
        changes=changes,
        unchanged=unchanged,
        refused=refused,
        warnings=tuple(warnings),
        editor=editor,
        facts=facts,
    )
    return plan, records


def plan(service: "SamsService", action: RecordAction, owner: str, owner_nr: int, selected: list[int]) -> ActionPlan:
    """What `action` would change. Writes nothing: the checks run and are
    rolled back, so records the detail page would refuse show up as such."""
    result, _records = _run(service, action, owner, owner_nr, selected, dry_run=True)
    return result


def apply(
    service: "SamsService",
    action: RecordAction,
    owner: str,
    owner_nr: int,
    selected: list[int],
    values: dict[str, str] | None = None,
) -> ActionOutcome:
    """Run `action` from the database's current state (the preview only
    informed the operator) and commit the records that pass their checks.
    `values` (ref → new text) is what an Edit action's dialog posted."""
    if action.edits_values and values is None:
        raise ValueError("Nothing was edited.")
    result, _records = _run(service, action, owner, owner_nr, selected, dry_run=False, values=values)
    return ActionOutcome(
        action=action,
        changed=len(result.changes),
        unchanged=result.unchanged,
        refused=result.refused,
    )


def parse_values(raw: str | None) -> dict[str, str] | None:
    """The Edit dialog's `{"48211": "Box 3", …}` (only the changed rows);
    blank → None."""
    if not raw or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("The edited values could not be read. Reload the page and try again.") from None
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in data.items()
    ):
        raise ValueError("The edited values could not be read. Reload the page and try again.")
    return data


def parse_selection(raw: str | None) -> list[int]:
    """`"12, 13,14"` → `[12, 13, 14]`; blank → `[]` (all rows)."""
    if not raw:
        return []
    numbers: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if not part.isdigit():
            raise ValueError(f"'{part}' is not a record number.")
        numbers.append(int(part))
    return list(dict.fromkeys(numbers))

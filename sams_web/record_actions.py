"""Record actions: named tasks on a record page that change many records.

A record action sets one field to one value on a set of records under the
page's record — e.g. *Set C/N Isotope Analysis* on the samples of a
project. Decisions: `docs/adr/0007-record-actions.md`.

- The **owner** is the page the action is run from (`project`,
  `submitter`). Its related table holds the **rows** the operator can tick
  (a project's samples, a submitter's projects). No ticks means all rows.
- The **child** is the kind of record the action writes. It is the row
  itself, or reached through it (the preparations of the ticked samples,
  the samples of the ticked projects).
- Every action is previewed first (`plan`), then run (`apply`). Both go
  through `SamsService.apply_many_and_commit`, i.e. through
  `apply_detail_update`, so a record that its detail page would refuse to
  save (an old sample with no type, say) is listed as refused and left
  alone; the rest are written in one commit.

**To add an action:** for a flag, one `_FLAGS` entry. Anything that is not
"set this field to this value" gets its own subclass of `RecordAction`
overriding `candidates` / `new_value`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

from sams_web.access import Permission
from sams_web.detail_update import DetailUpdateConfig
from sams_web.field_labels import field_label
from sams_web.viewmodels.detail_sections_sample_lab import PREPARATION_DETAIL, SAMPLE_DETAIL
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


KINDS: dict[str, Kind] = {
    "sample": Kind("sample", "sample", "samples", SAMPLE_DETAIL),
    "preparation": Kind("preparation", "preparation", "preparations", PREPARATION_DETAIL),
    "project": Kind("project", "project", "projects", PROJECT_DETAIL),
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
    if row_kind == "project" and child == "sample":
        return repo.list_samples_by_projects([row.project_nr for row in rows])
    if row_kind == "sample" and child == "preparation":
        return repo.list_preparations_by_samples([row.sample_nr for row in rows])
    if row_kind == "project" and child == "preparation":
        samples = repo.list_samples_by_projects([row.project_nr for row in rows])
        return repo.list_preparations_by_samples([s.sample_nr for s in samples])
    raise ValueError(f"A {row_kind} row cannot reach {child} records.")


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

    @property
    def field_title(self) -> str:
        return field_label(self.field)

    @property
    def title(self) -> str:
        return f"{self.verb} {self.field_title} on {KINDS[self.child].plural}"

    def current_value(self, record: Any) -> Any:
        return getattr(record, self.field, None)

    def is_unchanged(self, record: Any) -> bool:
        current = self.current_value(record)
        if self.value in (0, None):
            # "Clear" means "not set": an empty legacy value already is.
            return not current
        return current == self.value

    def form_for(self, record: Any) -> dict[str, str]:
        config = KINDS[self.child].config
        raw = "" if self.value is None else str(self.value)
        return {f"{config.prefix}{self.field}": raw}


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


_BOTH = ("project", "submitter")

_FLAGS: tuple[tuple[str, str, tuple[str, ...], Any], ...] = (
    ("sample", "c_n_isotop_a", _BOTH, _warn_cn_moved),
    ("sample", "dendro_a", _BOTH, None),
    ("sample", "s_no_leftover", _BOTH, None),
    ("preparation", "p_no_leftover", _BOTH, None),
    ("project", "return_to_sender", ("submitter",), None),
    ("project", "prep_return_to_sender", ("submitter",), None),
)

RECORD_ACTIONS: dict[str, RecordAction] = {
    action.key: action
    for child, field_name, owners, warn in _FLAGS
    for action in _flag_pair(child, field_name, owners, warn)
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
        group = groups.setdefault(
            action.child,
            {"kind": action.child, "title": KINDS[action.child].plural.capitalize(), "items": {}},
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
class ActionPlan:
    action: RecordAction
    row_kind: str
    row_count: int
    record_count: int
    changes: tuple[PlannedChange, ...]
    unchanged: int
    refused: tuple[Refused, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_json(self) -> dict[str, Any]:
        child = self.action.child
        return {
            "key": self.action.key,
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
        }


@dataclass(frozen=True)
class ActionOutcome:
    action: RecordAction
    changed: int
    unchanged: int
    refused: tuple[Refused, ...]

    def notice(self) -> str:
        child = self.action.child
        verb_done = {"Set": "set", "Clear": "cleared"}.get(self.action.verb, self.action.verb.lower())
        parts = [f"{self.action.field_title} {verb_done} on {self.changed} {noun(child, self.changed)}"]
        if self.unchanged:
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
) -> tuple[ActionPlan, list[Any]]:
    row_kind = OWNER_ROW_KIND[owner]
    rows = owner_rows(service, owner, owner_nr, selected)
    records = _reach(service, row_kind, rows, action.child)

    candidates: list[tuple[Any, RecordRef, str]] = []
    unchanged = 0
    warnings: list[str] = []
    for record in records:
        if action.is_unchanged(record):
            unchanged += 1
            continue
        if action.warn is not None:
            message = action.warn(record, action)
            if message:
                warnings.append(message)
        candidates.append((record, _ref_for(action.child, record), format_flag(action.current_value(record))))

    config = KINDS[action.child].config
    updates = [(ref.key, action.form_for(record)) for record, ref, _old in candidates]
    rejected = dict(service.apply_many_and_commit(config, updates, dry_run=dry_run)) if updates else {}

    new_text = format_flag(action.value)
    changes = tuple(
        PlannedChange(ref, old, new_text) for _record, ref, old in candidates if ref.key not in rejected
    )
    refused = tuple(
        Refused(ref, rejected[ref.key]) for _record, ref, _old in candidates if ref.key in rejected
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
    )
    return plan, records


def plan(service: "SamsService", action: RecordAction, owner: str, owner_nr: int, selected: list[int]) -> ActionPlan:
    """What `action` would change. Writes nothing: the checks run and are
    rolled back, so records the detail page would refuse show up as such."""
    result, _records = _run(service, action, owner, owner_nr, selected, dry_run=True)
    return result


def apply(service: "SamsService", action: RecordAction, owner: str, owner_nr: int, selected: list[int]) -> ActionOutcome:
    """Run `action` from the database's current state (the preview only
    informed the operator) and commit the records that pass their checks."""
    result, _records = _run(service, action, owner, owner_nr, selected, dry_run=False)
    return ActionOutcome(
        action=action,
        changed=len(result.changes),
        unchanged=result.unchanged,
        refused=result.refused,
    )


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

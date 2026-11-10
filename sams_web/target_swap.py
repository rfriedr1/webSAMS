"""Swap target info: exchange the `target_t` data of two targets (ADR-0008).

When two targets were mixed up — swapped on the graphitization rig, in the
magazine, or when typing — their data belongs to the other target. The
action on the target page exchanges it, group by group: the operator
ticks which groups move (all by default). The targets' identity
(`IDENTITY_FIELDS`) never moves.

Moving the *Measurement and Results* group also moves BATS' evaluation rows
(`calc_sample_t`) of the two targets onto each other, so the evaluation
still points at the measurement it describes. Nothing is recomputed: the
values are moved as they are (ADR-0003 stays intact — webSAMS computes no
result). The samples' averaged results (`sample_t`) are not touched; the
dialog says to re-evaluate both samples in BATS.

Every `Target` column is in exactly one group or in `IDENTITY_FIELDS`;
`tests/test_target_swap.py` fails on a new column that is in neither.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any, Iterable

from sams_web.field_labels import field_label
from sams_web.viewmodels.detail_sections_sample_lab import format_target_value

if TYPE_CHECKING:
    from sams_web.models import Target
    from sams_web.services import SamsService


TargetKey = tuple[int, int, int]


@dataclass(frozen=True)
class SwapGroup:
    key: str
    title: str
    fields: tuple[str, ...]


SWAP_GROUPS: tuple[SwapGroup, ...] = (
    SwapGroup("graphitization", "Graphitization", (
        "graph_batch", "graph_date", "reactor_nr", "combustion", "catalyst", "cathode_nr",
        "co2_init", "co2_final", "hydro_init", "hydro_final", "react_time", "temp", "weight",
        "graphitized", "target_pressed",
    )),
    SwapGroup("ea", "Elemental Analysis", ("weight_combustion", "conc_c", "conc_n")),
    SwapGroup("measurement", "Measurement and Results", (
        "magazine", "position", "precis", "cycle_min", "cycle_max", "le_curr", "he_curr",
        "c14_age", "c14_age_sig", "fm", "fm_sig", "dc13", "dc13_sig",
        "cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max", "cal_curve", "calcset", "editallowed",
    )),
    SwapGroup("comments", "Comments and Status", ("target_comment", "meas_comment", "old_info", "stop")),
)
GROUPS_BY_KEY = {group.key: group for group in SWAP_GROUPS}

MEASUREMENT_GROUP = "measurement"
"""Moving this group also moves the targets' `calc_sample_t` rows."""

IDENTITY_FIELDS: frozenset[str] = frozenset({"sample_nr", "prep_nr", "target_nr", "target_id"})
"""What a target *is*; never swapped. `target_id` names this target."""

FROZEN = 2
"""`editallowed` = 2: evaluated and frozen in BATS (ADR-0003)."""

RESULT_FIELDS = ("c14_age", "fm", "dc13")


def key_text(key: TargetKey) -> str:
    return ".".join(str(part) for part in key)


def target_href(key: TargetKey) -> str:
    return f"/samples/{key[0]}/preparations/{key[1]}/targets/{key[2]}"


def parse_groups(raw: Iterable[str] | None) -> tuple[str, ...]:
    """The ticked group keys in display order; `ValueError` when none or unknown."""
    wanted = {str(item).strip() for item in raw or () if str(item).strip()}
    unknown = wanted - GROUPS_BY_KEY.keys()
    if unknown:
        raise ValueError(f"Unknown group: {', '.join(sorted(unknown))}.")
    if not wanted:
        raise ValueError("Tick at least one group to swap.")
    return tuple(group.key for group in SWAP_GROUPS if group.key in wanted)


def _display(key: str, value: Any) -> str | None:
    shown = format_target_value(key, value)
    if shown is None:
        return None
    if isinstance(shown, datetime):
        return shown.strftime("%Y-%m-%d %H:%M") if key == "graph_date" else shown.strftime("%Y-%m-%d")
    if isinstance(shown, date):
        return shown.isoformat()
    if isinstance(shown, float):
        return f"{shown:.6f}".rstrip("0").rstrip(".")
    return str(shown)


def _load(service: "SamsService", first: TargetKey, second: TargetKey) -> tuple["Target", "Target"]:
    if first == second:
        raise ValueError("Pick another target: a target cannot be swapped with itself.")
    first_target = service.repo.get_target(*first)
    if first_target is None:
        raise ValueError(f"Target {key_text(first)} does not exist.")
    second_target = service.repo.get_target(*second)
    if second_target is None:
        raise ValueError(f"Target {key_text(second)} does not exist. Check sample, prep and target number.")
    return first_target, second_target


def _warnings(service: "SamsService", first: "Target", second: "Target", keys: tuple[TargetKey, TargetKey]) -> list[dict[str, str]]:
    """Notes for the dialog, each tied to the group whose tick makes it apply."""
    notes: list[dict[str, str]] = []
    frozen = [key_text(k) for k, t in zip(keys, (first, second)) if t.editallowed == FROZEN]
    if frozen:
        notes.append({
            "group": MEASUREMENT_GROUP,
            "text": (
                f"{'Target ' + frozen[0] + ' is' if len(frozen) == 1 else 'Both targets are'} frozen in BATS. "
                "The results move as they are, with their freeze state; nothing is recomputed."
            ),
        })
    if any(getattr(t, name) is not None for t in (first, second) for name in RESULT_FIELDS):
        samples = sorted({keys[0][0], keys[1][0]})
        named = " and ".join(f"sample {nr}" for nr in samples)
        notes.append({
            "group": MEASUREMENT_GROUP,
            "text": (
                f"The averaged results of {named} (C14 Age, FM …) were computed from their targets "
                "and are not changed here: re-evaluate in BATS after the swap."
            ),
        })
    counts = [service.repo.count_calc_sample_rows(*k) for k in keys]
    if any(counts):
        notes.append({
            "group": MEASUREMENT_GROUP,
            "text": (
                f"BATS evaluation rows (calc_sample_t) move with the results: {counts[0]} of this target, "
                f"{counts[1]} of target {key_text(keys[1])}."
            ),
        })
    return notes


def plan(service: "SamsService", first: TargetKey, second: TargetKey) -> dict[str, Any]:
    """The dialog's comparison: every group with both targets' values."""
    first_target, second_target = _load(service, first, second)
    second_sample = service.repo.get_sample(second[0])
    groups = []
    for group in SWAP_GROUPS:
        rows = []
        for name in group.fields:
            a = _display(name, getattr(first_target, name))
            b = _display(name, getattr(second_target, name))
            if a is None and b is None:
                continue
            rows.append({"key": name, "label": field_label(name), "this": a, "other": b, "same": a == b})
        groups.append({
            "key": group.key,
            "title": group.title,
            "rows": rows,
            "differs": sum(1 for row in rows if not row["same"]),
        })
    return {
        "this": {"ref": key_text(first), "href": target_href(first)},
        "other": {
            "ref": key_text(second),
            "href": target_href(second),
            "label": (second_sample.user_label or "") if second_sample else "",
        },
        "groups": groups,
        "warnings": _warnings(service, first_target, second_target, (first, second)),
    }


def apply(service: "SamsService", first: TargetKey, second: TargetKey, groups: tuple[str, ...]) -> str:
    """Swap the ticked groups and commit; returns the notice for the toast."""
    first_target, second_target = _load(service, first, second)
    attributes = [name for key in groups for name in GROUPS_BY_KEY[key].fields]
    service.swap_targets(
        first_target,
        second_target,
        attributes,
        move_calc_rows=(first, second) if MEASUREMENT_GROUP in groups else None,
    )
    titles = ", ".join(GROUPS_BY_KEY[key].title for key in groups)
    return f"Swapped {titles} with target {key_text(second)}."

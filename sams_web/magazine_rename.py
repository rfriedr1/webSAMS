"""Rename a magazine while it is still being planned (ADR-0009).

A magazine has no record of its own: its name is written into
`measprog_t` (the planned sequence), `target_t` (each target's magazine)
and `magazine_t` (the name list the database triggers keep). BATS' calc
sets (`calc_set_t`) name it too, but only once it was measured.

Only a magazine that was **not measured** may be renamed here: no calc set
names it and none of its targets has results or is frozen in BATS. A
measured magazine's name is also on the AMS and BATS computers (files,
calc sets), which this app cannot change. The new name must not be in use
in any of the tables: a rename never merges two magazines.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sams_web.models import MAGAZINE_NAME_LENGTH

if TYPE_CHECKING:
    from sams_web.services import SamsService


NAME_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
"""Letters, digits, `-` and `_`: every stored name but one is letters and
digits (`MA230505-1ST` has a dash)."""


def parse_new_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name:
        raise ValueError("Enter the new magazine name.")
    if len(name) > MAGAZINE_NAME_LENGTH:
        raise ValueError(f"A magazine name has at most {MAGAZINE_NAME_LENGTH} characters ({len(name)} entered).")
    if not NAME_PATTERN.match(name):
        raise ValueError("Use letters, digits, - and _ only (no spaces).")
    return name


def _resolve(service: "SamsService", magazine: str) -> str:
    current = service.repo.resolve_existing_magazine(magazine or "")
    if current is None:
        raise ValueError(f"Magazine {magazine.strip() or '(empty)'} does not exist.")
    return current


def _blockers(usage: dict[str, Any]) -> list[str]:
    """Why a magazine may not be renamed: it was measured."""
    reasons = []
    if usage["measured_targets"]:
        n = usage["measured_targets"]
        reasons.append(
            f"{n} of its targets {'has' if n == 1 else 'have'} measurement results or {'is' if n == 1 else 'are'} frozen in BATS."
        )
    if usage["calcsets"]:
        names = ", ".join(usage["calcsets"][:5]) + (" …" if len(usage["calcsets"]) > 5 else "")
        reasons.append(f"BATS has evaluated it (calc set {names}).")
    return reasons


def _check_new_name(service: "SamsService", current: str, raw: str | None) -> str:
    name = parse_new_name(raw)
    if name.lower() == current.lower():
        raise ValueError("That is the magazine's current name (upper and lower case count as the same).")
    taken = service.repo.magazine_name_taken(name)
    if taken is not None:
        raise ValueError(f"Magazine {taken} already exists. Pick a name no magazine uses: a rename never merges two magazines.")
    return name


def _changes(usage: dict[str, Any]) -> list[dict[str, Any]]:
    """What a rename writes, per table, for the dialog."""
    return [
        {"table": "measprog_t", "label": "Positions in the measurement sequence", "count": usage["sequence"]},
        {"table": "target_t", "label": "Targets", "count": usage["targets"]},
        {"table": "magazine_t", "label": "Magazine list", "count": usage["listed"]},
    ]


def plan(service: "SamsService", magazine: str, new_name: str | None = None) -> dict[str, Any]:
    """The dialog's preview: what would change, why it is refused, and
    whether `new_name` (when given) can be used. Writes nothing."""
    current = _resolve(service, magazine)
    usage = service.repo.magazine_usage(current)
    blocked = _blockers(usage)
    payload: dict[str, Any] = {
        "magazine": current,
        "max_length": MAGAZINE_NAME_LENGTH,
        "changes": _changes(usage),
        "blocked": blocked,
        "new_name": None,
        "error": None,
    }
    if new_name is not None and not blocked:
        try:
            payload["new_name"] = _check_new_name(service, current, new_name)
        except ValueError as exc:
            payload["error"] = str(exc)
    return payload


def apply(service: "SamsService", magazine: str, new_name: str | None) -> tuple[str, str]:
    """Check again and rename; returns (new name, notice for the toast)."""
    current = _resolve(service, magazine)
    blocked = _blockers(service.repo.magazine_usage(current))
    if blocked:
        raise ValueError(f"Magazine {current} was measured and cannot be renamed: {' '.join(blocked)}")
    name = _check_new_name(service, current, new_name)
    counts = service.rename_magazine(current, name)
    targets = counts["targets"]
    return name, (
        f"Renamed magazine {current} to {name} "
        f"({targets} target{'' if targets == 1 else 's'}, {counts['sequence']} sequence position{'' if counts['sequence'] == 1 else 's'})."
    )

"""Lab staff list (Setup → Lab Staff).

The app has no login yet, so "who did this" is a name picked from this
list: the operator of an EA check, the supervisor signing off a set of QC
results. `may_sign_off` marks the people allowed to sign off (lab director,
deputies). When Windows Authentication arrives (server guide §13) these
names should come from the authenticated user instead — see ADR-0005.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from sams_web.setup_sections import SETUP_SECTION_LAB_STAFF
from sams_web.setup_store import SetupStore

NAME_MAX_LENGTH = 40  # width of ea_check_t.operator / qc_signoff_t.signed_by


@dataclass(frozen=True)
class LabStaffMember:
    name: str
    may_sign_off: bool = False


class LabStaffStore:
    """Setup section `lab_staff`: `[{"name": str, "may_sign_off": bool}, …]`."""

    section_key = SETUP_SECTION_LAB_STAFF

    def __init__(self, setup_store: SetupStore) -> None:
        self._store = setup_store

    def load(self) -> list[LabStaffMember]:
        raw = self._store.get_section(self.section_key, default=[])
        members: list[LabStaffMember] = []
        seen: set[str] = set()
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, Mapping):
                continue
            name = str(item.get("name") or "").strip()[:NAME_MAX_LENGTH]
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            members.append(LabStaffMember(name=name, may_sign_off=bool(item.get("may_sign_off"))))
        return members

    def names(self) -> list[str]:
        return [m.name for m in self.load()]

    def signers(self) -> list[str]:
        return [m.name for m in self.load() if m.may_sign_off]

    def update(self, payload: Mapping[str, Any]) -> list[LabStaffMember]:
        """`payload`: parallel lists `names` and `roles` ("staff" | "signer").
        A blank name removes the row."""
        names = list(payload.get("names") or [])
        roles = list(payload.get("roles") or [])
        members: list[LabStaffMember] = []
        seen: set[str] = set()
        for index, raw_name in enumerate(names):
            name = str(raw_name or "").strip()
            if not name:
                continue
            if len(name) > NAME_MAX_LENGTH:
                raise ValueError(f"'{name}' is longer than {NAME_MAX_LENGTH} characters.")
            if name.lower() in seen:
                raise ValueError(f"'{name}' is listed twice.")
            seen.add(name.lower())
            role = str(roles[index] if index < len(roles) else "staff")
            members.append(LabStaffMember(name=name, may_sign_off=role == "signer"))
        self._store.set_section(
            self.section_key,
            [{"name": m.name, "may_sign_off": m.may_sign_off} for m in members],
        )
        return members

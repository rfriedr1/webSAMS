"""Who is using the app and what they may change (the access seam).

There is no login yet (see `docs/server_installation.md` §13: IIS in
front with Windows Authentication is planned). Until then every request
is served as one anonymous user whose role comes from `SAMS_ACCESS_ROLE`
(default `admin`, i.e. everyone may do everything, as before this module
existed). Setting it to `viewer` shows the app the way a view-only user
will see it.

When login arrives, `current_user()` is the one function that changes: it
will read the authenticated identity and look up its role. Everything
else — the route guards, the `can()` template global, the detail pages'
`can_edit` — already goes through it.

Rules:
- Every non-GET route carries `dependencies=[Depends(require(Permission.X))]`.
  `tests/test_access.py` fails on a write route without one.
- Templates hide write controls with `can("edit_records")`; the 403 from
  `require()` is the real guard, hiding only spares the user a button
  that would fail.

"User" here is the person signed in to webSAMS. A customer who submits
samples is a *Submitter* (`user_t`, see ADR-0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from fastapi import Depends, HTTPException, Request

from sams_web.config import get_settings


class Permission(str, Enum):
    """What a user may change. Reading is open to everyone on the network."""

    EDIT_RECORDS = "edit_records"
    """Samples, preparations, targets, projects, submitters: detail pages,
    benches, import, EA checks."""

    MANAGE_SETUP = "manage_setup"
    """Setup sections, test e-mails, maintenance jobs."""

    SIGN_OFF_QC = "sign_off_qc"
    """QC sign-offs. Lab Staff → *may sign off* still decides who is named."""


PERMISSION_LABELS: dict[Permission, str] = {
    Permission.EDIT_RECORDS: "change records",
    Permission.MANAGE_SETUP: "change the setup",
    Permission.SIGN_OFF_QC: "sign off QC checks",
}


class Role(str, Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset(),
    Role.EDITOR: frozenset({Permission.EDIT_RECORDS, Permission.SIGN_OFF_QC}),
    Role.ADMIN: frozenset(Permission),
}

DEFAULT_ROLE = Role.ADMIN


def parse_role(raw: str | None) -> Role:
    """`SAMS_ACCESS_ROLE` → Role. Blank means the default; anything else
    unknown is a configuration error, so the app refuses to start rather
    than silently granting (or withholding) rights."""
    value = (raw or "").strip().lower()
    if value == "":
        return DEFAULT_ROLE
    try:
        return Role(value)
    except ValueError as exc:
        allowed = ", ".join(role.value for role in Role)
        raise RuntimeError(f"SAMS_ACCESS_ROLE={raw!r} is not a role. Use one of: {allowed}.") from exc


@dataclass(frozen=True)
class AppUser:
    """The person using the app. `name` is None until login exists."""

    name: str | None
    role: Role

    def can(self, permission: Permission | str) -> bool:
        return Permission(permission) in ROLE_PERMISSIONS[self.role]


_STATE_KEY = "sams_user"


def current_user(request: Request) -> AppUser:
    """The user behind this request (cached on `request.state`).

    The single place that will read the Windows identity once IIS
    forwards it. Until then: anonymous, role from `SAMS_ACCESS_ROLE`.
    """
    cached = getattr(request.state, _STATE_KEY, None)
    if isinstance(cached, AppUser):
        return cached
    user = AppUser(name=None, role=get_settings().access_role)
    setattr(request.state, _STATE_KEY, user)
    return user


class PermissionDenied(HTTPException):
    def __init__(self, permission: Permission) -> None:
        self.permission = permission
        super().__init__(
            status_code=403,
            detail=f"You are not allowed to {PERMISSION_LABELS[permission]}.",
        )


def require(permission: Permission) -> Callable[[Request], AppUser]:
    """Route dependency: 403 unless the current user has `permission`.

    Use as `dependencies=[Depends(require(Permission.EDIT_RECORDS))]`.
    The returned function is tagged (`sams_permission`) so the route sweep
    in `tests/test_access.py` can tell a guarded route from an unguarded one.
    """

    def guard(request: Request) -> AppUser:
        user = current_user(request)
        if not user.can(permission):
            raise PermissionDenied(permission)
        return user

    guard.sams_permission = permission  # type: ignore[attr-defined]
    guard.__name__ = f"require_{permission.value}"
    return guard


def guarded(permission: Permission) -> list:
    """`dependencies=` value for a write route: `@router.post(..., dependencies=guarded(Permission.X))`."""
    return [Depends(require(permission))]


def request_can(request: Request | None, permission: Permission | str) -> bool:
    """`can()` for code that only has the request (templates, view builders)."""
    if request is None:
        return False
    return current_user(request).can(permission)

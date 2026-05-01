"""Magic Nav: parsing and dispatch for the global quick-jump bar.

The Magic Nav input box (in `templates/base.html`) accepts a small grammar:

- `123`              → opens sample 123
- `123.4`            → opens preparation 123/4
- `123.4.7`          → opens target 123/4/7
- `pr123`            → opens project 123
- `sub210`           → opens submitter 210
- `/prep`, `/graph`, `/ana` → opens the lab workflow page

This module owns:

- The **`NavTarget` sealed family** (`SampleNav`, `PreparationNav`,
  `TargetNav`, `ProjectNav`, `SubmitterNav`, `CommandNav`) — each carrying
  only the identifiers it actually needs, plus the resolved URL `target`.
- **`resolve_magic_identifier(raw)`** — the parser. Returns the matching
  `NavTarget` or `None` if the input doesn't fit any pattern.
- **`nav_exists(nav, service)`** and **`nav_not_found_message(nav)`** —
  match-based dispatchers. Each new `NavTarget` kind must be added to both.
- **`append_magic_feedback(url, ...)`** — attaches a `magic_identifier` /
  `magic_error` query pair onto a fallback URL when validation fails.
- **`build_magic_nav_rules()`** — produces the help-page rules table from
  the same prefix/command config the parser consumes.

The dispatchers expect a service object with the small set of `*_exists`
methods listed in `_NavService`. Tests can pass a stub satisfying that
shape.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


# ---- Config: prefix routes, labels, commands -----------------------------

MAGIC_IDENTIFIER_PREFIX_ROUTES: dict[str, tuple[str, str]] = {
    "pr": ("project", "/projects/{identifier}"),
    "sub": ("submitter", "/submitters/{identifier}"),
}
MAGIC_IDENTIFIER_PREFIX_LABELS: dict[str, str] = {
    "pr": "project number",
    "sub": "submitter number",
}
MAGIC_IDENTIFIER_SAMPLE_LABEL = "sample number"
MAGIC_IDENTIFIER_PREPARATION_LABEL = "preparation"
MAGIC_IDENTIFIER_TARGET_LABEL = "target"
MAGIC_IDENTIFIER_COMMAND_ROUTES: dict[str, str] = {
    "/prep": "/lab/preparation",
    "/graph": "/lab/graphitization",
    "/ana": "/lab/analysis",
}
MAGIC_IDENTIFIER_COMMAND_LABELS: dict[str, str] = {
    "/prep": "magic command: preparation",
    "/graph": "magic command: graphitization",
    "/ana": "magic command: analysis",
}


# ---- Sealed family --------------------------------------------------------


@dataclass(frozen=True)
class SampleNav:
    target: str
    sample_nr: int


@dataclass(frozen=True)
class PreparationNav:
    target: str
    sample_nr: int
    prep_nr: int


@dataclass(frozen=True)
class TargetNav:
    target: str
    sample_nr: int
    prep_nr: int
    target_nr: int


@dataclass(frozen=True)
class ProjectNav:
    target: str
    project_nr: int


@dataclass(frozen=True)
class SubmitterNav:
    target: str
    user_nr: int


@dataclass(frozen=True)
class CommandNav:
    target: str
    command: str


NavTarget = SampleNav | PreparationNav | TargetNav | ProjectNav | SubmitterNav | CommandNav


# ---- Parser ---------------------------------------------------------------


def resolve_magic_identifier(raw: str) -> NavTarget | None:
    """Parse `raw` into a `NavTarget`, or return `None` if no pattern matches.

    Patterns tried in order: command literal (`/prep`), 3-part numeric
    (`123.4.7`), 2-part numeric (`123.4`), bare digits (`123`), prefixed
    (`pr123`, `sub210`). Comparison is case-insensitive on the input.
    """
    value = raw.strip().lower()
    if value == "":
        return None

    command_target = MAGIC_IDENTIFIER_COMMAND_ROUTES.get(value)
    if command_target is not None:
        return CommandNav(target=command_target, command=value)

    target_ref = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value)
    if target_ref is not None:
        sample_nr, prep_nr, target_nr = (int(part) for part in target_ref.groups())
        return TargetNav(
            target=f"/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}",
            sample_nr=sample_nr,
            prep_nr=prep_nr,
            target_nr=target_nr,
        )

    prep_ref = re.fullmatch(r"(\d+)\.(\d+)", value)
    if prep_ref is not None:
        sample_nr, prep_nr = (int(part) for part in prep_ref.groups())
        return PreparationNav(
            target=f"/samples/{sample_nr}/preparations/{prep_nr}",
            sample_nr=sample_nr,
            prep_nr=prep_nr,
        )

    if re.fullmatch(r"\d+", value):
        sample_nr = int(value)
        return SampleNav(
            target=f"/samples/{sample_nr}",
            sample_nr=sample_nr,
        )

    prefixed = re.fullmatch(r"([a-z]+)[\s:_-]*(\d+)", value)
    if prefixed is None:
        return None
    prefix, identifier_str = prefixed.groups()
    route_spec = MAGIC_IDENTIFIER_PREFIX_ROUTES.get(prefix)
    if route_spec is None:
        return None
    entity_kind, target_template = route_spec
    identifier = int(identifier_str)
    target_url = target_template.format(identifier=identifier)
    if entity_kind == "project":
        return ProjectNav(target=target_url, project_nr=identifier)
    if entity_kind == "submitter":
        return SubmitterNav(target=target_url, user_nr=identifier)
    return None


# ---- Dispatchers ----------------------------------------------------------


class _NavService(Protocol):
    def sample_exists(self, sample_nr: int) -> bool: ...
    def preparation_exists(self, sample_nr: int, prep_nr: int) -> bool: ...
    def target_exists(self, sample_nr: int, prep_nr: int, target_nr: int) -> bool: ...
    def project_exists(self, project_nr: int) -> bool: ...
    def submitter_exists(self, user_nr: int) -> bool: ...


def nav_exists(nav: NavTarget, service: _NavService) -> bool:
    """Return True if the entity referenced by `nav` exists.

    `CommandNav` targets are pre-built routes that always exist.
    """
    match nav:
        case CommandNav():
            return True
        case SampleNav(sample_nr=s):
            return service.sample_exists(s)
        case PreparationNav(sample_nr=s, prep_nr=p):
            return service.preparation_exists(s, p)
        case TargetNav(sample_nr=s, prep_nr=p, target_nr=t):
            return service.target_exists(s, p, t)
        case ProjectNav(project_nr=p):
            return service.project_exists(p)
        case SubmitterNav(user_nr=u):
            return service.submitter_exists(u)


def nav_not_found_message(nav: NavTarget) -> str:
    """User-facing not-found message keyed to the identifier shape."""
    match nav:
        case CommandNav():
            return ""  # commands always exist; never reached
        case SampleNav(sample_nr=s):
            return f"Sample #{s} was not found."
        case PreparationNav(sample_nr=s, prep_nr=p):
            return f"Preparation {s}.{p} was not found."
        case TargetNav(sample_nr=s, prep_nr=p, target_nr=t):
            return f"Target {s}.{p}.{t} was not found."
        case ProjectNav(project_nr=p):
            return f"Project #{p} was not found."
        case SubmitterNav(user_nr=u):
            return f"Submitter #{u} was not found."


# ---- Feedback URL helper --------------------------------------------------


def append_magic_feedback(url: str, entered_value: str, error_message: str) -> str:
    """Attach `magic_identifier=<entered>` and `magic_error=<message>` query
    parameters onto `url`, preserving any existing query."""
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["magic_identifier"] = entered_value
    query["magic_error"] = error_message
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


# ---- Help-page rules ------------------------------------------------------


def build_magic_nav_rules() -> list[dict[str, str]]:
    """Build the rules table shown on the Help page from the same config
    the parser uses."""
    rules: list[dict[str, str]] = [
        {
            "pattern": "digits only",
            "example": "45230",
            "description": f"Opens sample detail (label: {MAGIC_IDENTIFIER_SAMPLE_LABEL}).",
        },
        {
            "pattern": "sample.prep",
            "example": "45230.1",
            "description": (
                "Opens preparation detail for sample/preparation "
                f"(label: {MAGIC_IDENTIFIER_PREPARATION_LABEL})."
            ),
        },
        {
            "pattern": "sample.prep.target",
            "example": "45230.1.1",
            "description": (
                "Opens target detail for sample/preparation/target "
                f"(label: {MAGIC_IDENTIFIER_TARGET_LABEL})."
            ),
        },
    ]
    for prefix in sorted(MAGIC_IDENTIFIER_PREFIX_LABELS.keys()):
        route_spec = MAGIC_IDENTIFIER_PREFIX_ROUTES.get(prefix)
        if route_spec is None:
            continue
        entity_kind, _target_template = route_spec
        rules.append(
            {
                "pattern": f"{prefix}<number>",
                "example": f"{prefix}123",
                "description": (
                    f"Opens {entity_kind} detail "
                    f"(label: {MAGIC_IDENTIFIER_PREFIX_LABELS.get(prefix, 'unknown ID')})."
                ),
            }
        )
    for command in sorted(MAGIC_IDENTIFIER_COMMAND_ROUTES.keys()):
        command_target = MAGIC_IDENTIFIER_COMMAND_ROUTES[command]
        label = MAGIC_IDENTIFIER_COMMAND_LABELS.get(command, "magic command")
        rules.append(
            {
                "pattern": command,
                "example": command,
                "description": f"Runs {label} and opens {command_target}.",
            }
        )
    return rules


INVALID_MAGIC_NAV_MESSAGE = (
    "Invalid Magic Nav ID. Use 123, 45230.1, 45230.1.1, "
    "pr123, sub210, /prep, /graph, or /ana."
)


__all__ = [
    "SampleNav",
    "PreparationNav",
    "TargetNav",
    "ProjectNav",
    "SubmitterNav",
    "CommandNav",
    "NavTarget",
    "resolve_magic_identifier",
    "nav_exists",
    "nav_not_found_message",
    "append_magic_feedback",
    "build_magic_nav_rules",
    "INVALID_MAGIC_NAV_MESSAGE",
    "MAGIC_IDENTIFIER_PREFIX_ROUTES",
    "MAGIC_IDENTIFIER_PREFIX_LABELS",
    "MAGIC_IDENTIFIER_SAMPLE_LABEL",
    "MAGIC_IDENTIFIER_PREPARATION_LABEL",
    "MAGIC_IDENTIFIER_TARGET_LABEL",
    "MAGIC_IDENTIFIER_COMMAND_ROUTES",
    "MAGIC_IDENTIFIER_COMMAND_LABELS",
]

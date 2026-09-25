"""Service-layer entry points for the import wizard.

Keeps the router thin: it hands over bytes and gets back a
JSON-serialisable review payload, or hands over an approved payload and
gets back an `ImportResult`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sams_web.import_settings import EmailSettingsStore, ImportHeadingStore
from sams_web.sample_import.commit import (
    DEFAULT_PROJECT_PRICE,
    DEFAULT_PROJECT_PRIORITY,
    DEFAULT_TURNAROUND_DAYS,
    PREP_STEP_FIELDS,
    ImportResult,
    commit_import,
)
from sams_web.sample_import.draft import ImportDraft
from sams_web.sample_import.matching import (
    candidate_search_terms,
    find_submitter_candidates,
    resolve_lookup_column,
)
from sams_web.sample_import.parser import parse_grid
from sams_web.sample_import.vocabulary import (
    CONTACT_FIELD_LABELS,
    EDITABLE_CONTACT_FIELDS,
    LANGUAGE_OPTIONS,
    MULTILINE_CONTACT_FIELDS,
    normalize_label,
    suggest_from_choices,
)
from sams_web.sample_import.workbook import load_grids, pick_submission_grid

#: Cap on candidate rows pulled from the DB for scoring.
CANDIDATE_QUERY_LIMIT = 60

#: Priority values. `project_t.priority` has no lookup table; the legacy
#: UI used a three-way radio group.
PRIORITY_OPTIONS: tuple[tuple[int, str], ...] = (
    (0, "Low"),
    (1, "Normal"),
    (2, "High"),
)


def field_registry(service: Any):
    """Importable fields for this request: built-ins + Setup definitions."""
    return ImportHeadingStore(service.setup_store).registry()


def _contact_field_specs() -> list[dict[str, Any]]:
    """Field descriptors for the editable new-submitter form."""
    return [
        {
            "key": key,
            "label": CONTACT_FIELD_LABELS.get(key, key),
            "kind": (
                "textarea"
                if key in MULTILINE_CONTACT_FIELDS
                else "select"
                if key == "language"
                else "email"
                if key == "email"
                else "text"
            ),
            "options": (
                [{"value": code, "label": label} for code, label in LANGUAGE_OPTIONS]
                if key == "language"
                else []
            ),
        }
        for key in EDITABLE_CONTACT_FIELDS
    ]


def _submitter_row_summary(row: Any) -> dict[str, Any]:
    """Compact shape used by the browse-and-pick submitter list."""
    last = (row.last_name or "").strip()
    first = (row.first_name or "").strip()
    return {
        "user_nr": int(row.user_nr),
        "display_name": f"{last}, {first}".strip(", ") or "(unnamed)",
        "organisation": (row.organisation or "").strip(),
        "institute": (row.institute or "").strip(),
        "email": (row.email or "").strip(),
        "town": (row.town or "").strip(),
        "country": (row.country or "").strip(),
    }


def _candidates_for(service: Any, parsed: dict[str, str]) -> list[dict[str, Any]]:
    """Score existing submitters against a parsed contact block."""
    if not parsed:
        return []
    repo = service.repo
    rows: dict[int, Any] = {}
    email = (parsed.get("email") or "").strip()
    if email:
        for row in repo.list_submitters(query=email, limit=CANDIDATE_QUERY_LIMIT):
            rows[int(row.user_nr)] = row
    for term in candidate_search_terms(parsed):
        for row in repo.list_submitters(query=term, limit=CANDIDATE_QUERY_LIMIT):
            rows[int(row.user_nr)] = row
    return [c.as_dict() for c in find_submitter_candidates(parsed, list(rows.values()))]


def search_submitters(service: Any, query: str, limit: int = 40) -> list[dict[str, Any]]:
    """Backing call for the wizard's 'browse all submitters' picker."""
    rows = service.repo.list_submitters(query=query or None, limit=limit)
    return [_submitter_row_summary(row) for row in rows]


def projects_for_submitter(service: Any, user_nr: int) -> list[dict[str, Any]]:
    """Existing projects for a submitter, for the duplicate-project check."""
    projects = service.repo.find_projects_for_submitter(int(user_nr))
    return [
        {
            "project_nr": int(p.project_nr),
            "project": (p.project or "").strip(),
            "status": (p.status or "").strip(),
            "in_date": p.in_date.isoformat() if p.in_date else "",
            "desired_date": p.desired_date.isoformat() if p.desired_date else "",
        }
        for p in projects
    ]


def suggest_project_variant(name: str, *, today: date | None = None) -> str:
    """Propose `<name>_<Month>_<Year>` for a follow-up batch.

    Used when the submitter already has a project with this name and the
    operator wants a *separate* project rather than appending — matching
    the convention the lab already uses by hand.
    """
    today = today or date.today()
    suffix = f"_{today.strftime('%B')}_{today.year}"
    base = (name or "").strip()
    if base.endswith(suffix):
        return base
    return f"{base}{suffix}"


def _match_project_names(
    parsed_name: str, existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Flag existing projects whose name looks like the incoming one."""
    key = normalize_label(parsed_name)
    if not key:
        return []
    matches: list[dict[str, Any]] = []
    for project in existing:
        other = normalize_label(project["project"])
        if not other:
            continue
        if other == key:
            matches.append({**project, "match": "exact"})
        elif other.startswith(key) or key.startswith(other):
            matches.append({**project, "match": "similar"})
    return matches


def parse_submission(
    service: Any, data: bytes, *, filename: str
) -> tuple[ImportDraft, dict[str, Any]]:
    """Parse an uploaded workbook and enrich it for the review step.

    Returns `(draft, review_payload)`. The payload is everything the
    browser needs to render the review UI: the draft, submitter and
    invoice candidates, lookup resolutions, and every option list that
    populates a dropdown.
    """
    grids = load_grids(data, filename=filename)
    grid = pick_submission_grid(grids)
    registry = field_registry(service)
    draft = parse_grid(grid, file_name=filename, sample_synonyms=registry.synonyms)

    repo = service.repo

    # --- Submitter and invoice candidates -----------------------------
    submitter_candidates = _candidates_for(service, draft.submitter.values)
    invoice_candidates = _candidates_for(service, draft.invoice.values)

    # --- Existing projects for a confidently matched submitter --------
    strong = next((c for c in submitter_candidates if c["is_strong"]), None)
    existing_projects: list[dict[str, Any]] = []
    project_name_matches: list[dict[str, Any]] = []
    if strong:
        existing_projects = projects_for_submitter(service, strong["user_nr"])
        project_name_matches = _match_project_names(
            draft.project.values.get("project", ""), existing_projects
        )

    # --- Lookup resolutions for the sample columns --------------------
    lookup_options: dict[str, list[str]] = {}
    lookup_resolutions: dict[str, dict[str, Any]] = {}
    for field_name, getter in registry.lookup_fields.items():
        options = list(getattr(repo, getter)())
        lookup_options[field_name] = options
        raw_values = [s.values.get(field_name) for s in draft.samples]
        lookup_resolutions[field_name] = {
            raw: resolution.as_dict()
            for raw, resolution in resolve_lookup_column(raw_values, options).items()
        }

    # --- Lab-value pre-matching from the submitter's own material -----
    #
    # The customer writes their vocabulary ("collagen"); the lab records
    # its own ("bone"). Suggest a lab type/material/fraction per distinct
    # submitter material so the operator confirms rather than types.
    material_options = lookup_options["material"]
    type_options = lookup_options["type"]
    fraction_options = lookup_options["fraction"]
    group_suggestions: dict[str, dict[str, Any]] = {}
    for sample in draft.samples:
        raw = str(sample.values.get("material") or "").strip()
        if not raw or raw in group_suggestions:
            continue
        group_suggestions[raw] = {
            "material": [c for c, _ in suggest_from_choices(raw, material_options, limit=4)],
            "type": [c for c, _ in suggest_from_choices(raw, type_options, limit=4)],
            "fraction": [c for c, _ in suggest_from_choices(raw, fraction_options, limit=4)],
        }

    # --- Project defaults the sheet does not carry --------------------
    today = date.today()
    project_values = dict(draft.project.values)
    project_values.setdefault("in_date", today.isoformat())
    project_values.setdefault(
        "desired_date", (today + timedelta(days=DEFAULT_TURNAROUND_DAYS)).isoformat()
    )
    project_values.setdefault("priority", DEFAULT_PROJECT_PRIORITY)
    project_values.setdefault("price", DEFAULT_PROJECT_PRICE)

    email_store = EmailSettingsStore(service.setup_store)

    payload: dict[str, Any] = {
        "draft": draft.as_dict(),
        "project_defaults": project_values,
        "project_variant_suggestion": suggest_project_variant(
            draft.project.values.get("project", "")
        ),
        "submitter_candidates": submitter_candidates,
        "invoice_candidates": invoice_candidates,
        "existing_projects": existing_projects,
        "project_name_matches": project_name_matches,
        "lookup_options": lookup_options,
        "lookup_resolutions": lookup_resolutions,
        "group_suggestions": group_suggestions,
        "prep_step_fields": list(PREP_STEP_FIELDS),
        # `get_methods()` orders by the legacy `method_t.indexnr`, which is
        # insertion order rather than anything meaningful to look up. The
        # wizard sets five prep steps per group from a 40+ item list, so
        # it sorts alphabetically instead; the bench screens keep the
        # legacy order.
        "method_options": sorted(repo.get_methods(), key=lambda m: str(m).casefold()),
        "project_options": {
            "project_type": list(repo.get_project_types()),
            "research": list(repo.get_research_values()),
            "report_type": list(repo.get_report_types()),
            "supervisor": list(repo.get_advisors()),
            "priority": [{"value": v, "label": lbl} for v, lbl in PRIORITY_OPTIONS],
        },
        "contact_fields": _contact_field_specs(),
        "field_labels": {
            "sample": registry.labels,
            "contact": CONTACT_FIELD_LABELS,
        },
        "mappable_fields": [
            {"value": f.key, "label": f.label, "builtin": f.builtin}
            for f in registry.fields.values()
        ],
        "lookup_fields": list(registry.lookup_fields),
        "email_configured": email_store.is_configured(),
    }
    return draft, payload


def commit_submission(service: Any, payload: dict[str, Any]) -> ImportResult:
    """Commit an operator-approved import payload."""
    return commit_import(service, payload, registry=field_registry(service))


__all__ = [
    "field_registry",
    "PRIORITY_OPTIONS",
    "commit_submission",
    "parse_submission",
    "projects_for_submitter",
    "search_submitters",
    "suggest_project_variant",
]

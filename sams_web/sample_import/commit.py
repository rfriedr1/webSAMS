"""Turn an operator-approved import payload into database records.

Shape of the write, mirroring the legacy Delphi importer's data model
(see `docs/adr/` and the legacy `InsertNewSamplesInDb`):

    submitter (user_t)                  reused or created
      └─ invoice recipient (user_t)     only when billing differs
      └─ project (project_t)            always created
           └─ sample (sample_t) × N     each with:
                └─ preparation #1
                     └─ target #1

Everything runs inside one transaction: a failure part-way through
leaves no orphaned submitter or half-filled project behind.

The payload comes from the browser after the review step, so every
value is re-validated here. Nothing is trusted because it "was parsed
already" — the operator can edit any field in between.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from sams_web.sample_import.vocabulary import IMPORTABLE_SAMPLE_FIELDS

# --- Intake defaults -------------------------------------------------------
#
# Values the sheet never carries but every new record needs. Taken from
# what the legacy importer wrote and confirmed against recent rows in
# the live database.

DEFAULT_PROJECT_STATUS = "planned"
DEFAULT_PROJECT_PRIORITY = 1          # 0 Low / 1 Normal / 2 High
DEFAULT_PROJECT_PRICE = "300"
DEFAULT_TURNAROUND_DAYS = 90
DEFAULT_LOOKUP_VALUE = "undefined"    # material_t / sampletype_t / fraction_t row
DEFAULT_SAMPLE_EDITABLE = 1
DEFAULT_SAMPLE_NOT_TOBEDATED = 0

#: `user_t.correspondance` = 1 means "send correspondence here" (the
#: submitter); `user_t.invoice` = 1 means "this address may be billed".
SUBMITTER_FLAGS_SAME_ADDRESS = {"invoice": 1, "correspondance": 1}
SUBMITTER_FLAGS_SEPARATE_INVOICE = {"invoice": 0, "correspondance": 1}
INVOICE_RECIPIENT_FLAGS = {"invoice": 1, "correspondance": 0}

#: Contact fields we will write to `user_t`. Wider than what the sheet
#: carries: salutation / title / language / user_comment are lab-side
#: attributes the operator fills in on the review step (language decides
#: which confirmation-e-mail template is used).
CONTACT_COLUMNS: tuple[str, ...] = (
    "salutation",
    "title",
    "language",
    "user_comment",
    "first_name",
    "last_name",
    "organisation",
    "institute",
    "address_1",
    "address_2",
    "town",
    "postcode",
    "country",
    "phone_1",
    "phone_2",
    "fax",
    "email",
    "www",
)


class ImportCommitError(ValueError):
    """Raised when the approved payload cannot be committed."""


@dataclass
class ImportResult:
    """What the commit produced, for the success screen."""

    project_nr: int
    project_name: str
    user_nr: int
    submitter_created: bool
    submitter_name: str
    invoice_nr: int | None = None
    invoice_created: bool = False
    project_created: bool = True
    sample_nrs: list[int] = field(default_factory=list)
    sample_labels: list[str] = field(default_factory=list)
    skipped_rows: list[int] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return len(self.sample_nrs)

    def as_dict(self) -> dict[str, Any]:
        return {
            "project_nr": self.project_nr,
            "project_name": self.project_name,
            "project_url": f"/projects/{self.project_nr}",
            "user_nr": self.user_nr,
            "submitter_created": self.submitter_created,
            "submitter_name": self.submitter_name,
            "submitter_url": f"/submitters/{self.user_nr}",
            "invoice_nr": self.invoice_nr,
            "invoice_created": self.invoice_created,
            "project_created": self.project_created,
            "sample_labels": list(self.sample_labels),
            "sample_nrs": list(self.sample_nrs),
            "sample_count": self.sample_count,
            "first_sample_url": (
                f"/samples/{self.sample_nrs[0]}" if self.sample_nrs else None
            ),
            "skipped_rows": list(self.skipped_rows),
        }


def _clean(value: Any, *, max_length: int | None = None) -> str | None:
    """Trim, drop empties, and clamp to the DB column width.

    Truncating here (rather than letting MySQL do it, or raising) keeps
    a single over-long address line from failing an otherwise good
    import of 60 samples.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if max_length is not None and len(text) > max_length:
        text = text[:max_length]
    return text


# Column widths taken from the live MySQL schema via
# `information_schema.COLUMNS`, NOT from `models.py` — the ORM
# over-declares several of these (it says `user_label` is 255 where the
# table is 100, and `material` 60 where the table is 20). Clamping to
# the ORM's numbers would let MySQL reject the whole import.
_CONTACT_WIDTHS: dict[str, int] = {
    "salutation": 10,
    "title": 20,
    "language": 2,
    # user_comment is TEXT; no clamp.
    "first_name": 40,
    "last_name": 60,
    "organisation": 100,
    "institute": 100,
    "address_1": 80,
    "address_2": 80,
    "town": 30,
    "postcode": 10,
    "country": 30,
    "phone_1": 30,
    "phone_2": 30,
    "fax": 30,
    "email": 80,
    "www": 60,
}

_SAMPLE_WIDTHS: dict[str, int] = {
    "user_label": 100,
    "user_label_nr": 40,
    "user_desc1": 100,
    "user_desc2": 40,
    "material": 20,
    "type": 20,
    "fraction": 20,
    "pre_sub_treat": 40,
}

_PROJECT_WIDTHS: dict[str, int] = {
    "project": 100,
    "price": 20,
    "order_nr": 60,
}

#: Sample columns backed by a lookup table, and the repo getter that
#: lists their allowed values. Free text must never reach these columns:
#: they are a controlled vocabulary that the rest of the app (search
#: facets, dashboard standards, calibration rules) relies on.
_LOOKUP_FIELD_GETTERS: dict[str, str] = {
    "material": "get_materials",
    "type": "get_sample_types",
    "fraction": "get_fractions",
}


#: Project columns backed by a lookup table.
_PROJECT_LOOKUP_GETTERS: dict[str, str] = {
    "project_type": "get_project_types",
    "research": "get_research_values",
    "report_type": "get_report_types",
    "supervisor": "get_advisors",
}

#: Preparation step columns written to `preparation_t`.
PREP_STEP_FIELDS: tuple[str, ...] = (
    "step1_method",
    "step2_method",
    "step3_method",
    "step4_method",
    "step5_method",
)


def _lookup_or_default(
    raw: Any, allowed: dict[str, str], *, default: Any = DEFAULT_LOOKUP_VALUE
) -> Any:
    """Resolve a value against a controlled vocabulary, case-insensitively.

    Returns `default` for anything not in the list. Applied to every
    lookup-backed column so a hand-edited browser payload can never
    introduce free text into an enum column.
    """
    if raw is None:
        return default
    key = str(raw).strip().lower()
    if not key:
        return default
    return allowed.get(key, default)


def _contact_payload(values: dict[str, Any], sanitizer: Any) -> dict[str, Any]:
    """Build a `user_t` insert payload from a contact block."""
    payload: dict[str, Any] = {}
    for column in CONTACT_COLUMNS:
        cleaned = _clean(values.get(column), max_length=_CONTACT_WIDTHS.get(column))
        if cleaned is not None:
            # Same crude injection/format guard the rest of the app uses.
            cleaned = sanitizer.replace_bad_characters(cleaned)
            cleaned = _clean(cleaned, max_length=_CONTACT_WIDTHS.get(column))
        payload[column] = cleaned
    return payload


def _parse_iso_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


@dataclass(frozen=True)
class _Party:
    """A resolved `user_t` row: reused or freshly created."""

    user_nr: int
    name: str
    created: bool


@dataclass(frozen=True)
class _ProjectRef:
    project_nr: int
    name: str
    created: bool


@dataclass(frozen=True)
class _ImportPlan:
    """Everything validated up front, before a single row is written."""

    project_name: str
    rows: list[tuple[int, dict[str, Any]]]
    skipped_rows: list[int]


def _party_name(row: Any) -> str:
    return f"{row.last_name or ''}, {row.first_name or ''}".strip(", ") or "(unnamed)"


def _validate_payload(payload: dict[str, Any]) -> _ImportPlan:
    """Reject anything that would fail part-way; nothing is written yet."""
    project_input = payload.get("project") or {}
    project_name = _clean(project_input.get("project"), max_length=_PROJECT_WIDTHS["project"])
    if not project_name:
        raise ImportCommitError("A project name is required.")

    all_rows = payload.get("samples") or []
    rows = [r for r in all_rows if r.get("include", True)]
    if not rows:
        raise ImportCommitError("No samples were selected for import.")

    prepared: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        values = row.get("values") or {}
        label = _clean(values.get("user_label"), max_length=_SAMPLE_WIDTHS["user_label"])
        if not label:
            raise ImportCommitError(
                f"Row {row.get('row_number', '?')} has no sample name. "
                "Fix or exclude it before importing."
            )
        prepared.append((int(row.get("row_number") or 0), values))

    skipped = [int(r.get("row_number") or 0) for r in all_rows if not r.get("include", True)]
    return _ImportPlan(project_name=project_name, rows=prepared, skipped_rows=skipped)


def _resolve_submitter(repo: Any, session: Any, payload: dict[str, Any], sanitizer: Any) -> _Party:
    submitter_input = payload.get("submitter") or {}
    existing_user_nr = submitter_input.get("user_nr")
    if existing_user_nr:
        submitter = repo.get_submitter(int(existing_user_nr))
        if submitter is None:
            raise ImportCommitError(
                f"Submitter #{existing_user_nr} no longer exists. Re-run the review step."
            )
        return _Party(int(submitter.user_nr), _party_name(submitter), created=False)

    values = submitter_input.get("values") or {}
    if not _clean(values.get("last_name")):
        raise ImportCommitError("A submitter last name is required to create a new submitter.")
    invoice_enabled = bool((payload.get("invoice") or {}).get("enabled"))
    flags = SUBMITTER_FLAGS_SEPARATE_INVOICE if invoice_enabled else SUBMITTER_FLAGS_SAME_ADDRESS
    submitter = repo.create_submitter({**_contact_payload(values, sanitizer), **flags})
    session.flush()
    return _Party(int(submitter.user_nr), _party_name(submitter), created=True)


def _resolve_invoice(
    repo: Any, session: Any, payload: dict[str, Any], sanitizer: Any
) -> _Party | None:
    """The invoice recipient is a *second* `user_t` row, matched independently."""
    invoice_input = payload.get("invoice") or {}
    if not invoice_input.get("enabled"):
        return None
    existing_nr = invoice_input.get("user_nr")
    if existing_nr:
        row = repo.get_submitter(int(existing_nr))
        if row is None:
            raise ImportCommitError(f"Invoice recipient #{existing_nr} no longer exists.")
        return _Party(int(row.user_nr), _party_name(row), created=False)

    values = invoice_input.get("values") or {}
    if not any(_clean(v) for v in values.values()):
        return None
    row = repo.create_submitter({**_contact_payload(values, sanitizer), **INVOICE_RECIPIENT_FLAGS})
    session.flush()
    return _Party(int(row.user_nr), _party_name(row), created=True)


def _resolve_project(
    repo: Any,
    session: Any,
    payload: dict[str, Any],
    *,
    project_name: str,
    user_nr: int,
    invoice_nr: int | None,
    today: date,
    sanitizer: Any,
) -> _ProjectRef:
    project_input = payload.get("project") or {}

    # Appending to an existing project skips creation entirely: the
    # operator chose it on the review step because this is a follow-up
    # batch for a project that is already running.
    existing_project_nr = project_input.get("existing_project_nr")
    if existing_project_nr:
        project = repo.get_project(int(existing_project_nr))
        if project is None:
            raise ImportCommitError(
                f"Project #{existing_project_nr} no longer exists. Re-run the review step."
            )
        if project.user_nr and int(project.user_nr) != user_nr:
            raise ImportCommitError(
                f"Project #{existing_project_nr} belongs to a different submitter."
            )
        return _ProjectRef(int(project.project_nr), project.project or project_name, created=False)

    lookups = {
        field_name: {str(o).strip().lower(): str(o) for o in getattr(repo, getter)()}
        for field_name, getter in _PROJECT_LOOKUP_GETTERS.items()
    }
    in_date = _parse_iso_date(project_input.get("in_date")) or today
    desired_date = _parse_iso_date(project_input.get("desired_date")) or (
        in_date + timedelta(days=DEFAULT_TURNAROUND_DAYS)
    )
    try:
        priority = int(project_input.get("priority", DEFAULT_PROJECT_PRIORITY))
    except (TypeError, ValueError):
        priority = DEFAULT_PROJECT_PRIORITY

    project = repo.create_project(
        {
            "project": sanitizer.replace_bad_characters(project_name)[: _PROJECT_WIDTHS["project"]],
            "user_nr": user_nr,
            "invoice_nr": invoice_nr,
            "in_date": in_date,
            "desired_date": desired_date,
            "out_date": None,
            "status": DEFAULT_PROJECT_STATUS,
            "priority": priority,
            "price": _clean(project_input.get("price"), max_length=_PROJECT_WIDTHS["price"])
            or DEFAULT_PROJECT_PRICE,
            "project_comment": _clean(project_input.get("project_comment")),
            "order_nr": _clean(project_input.get("order_nr"), max_length=_PROJECT_WIDTHS["order_nr"]),
            "project_type": _lookup_or_default(project_input.get("project_type"), lookups["project_type"]),
            "research": _lookup_or_default(project_input.get("research"), lookups["research"]),
            "report_type": _lookup_or_default(project_input.get("report_type"), lookups["report_type"]),
            "supervisor": _lookup_or_default(
                project_input.get("supervisor"), lookups["supervisor"], default=None
            ),
            "free_of_charge": 1 if project_input.get("free_of_charge") else 0,
            "return_to_sender": 1 if project_input.get("return_to_sender") else 0,
            "prep_return_to_sender": 1 if project_input.get("prep_return_to_sender") else 0,
        }
    )
    session.flush()
    return _ProjectRef(int(project.project_nr), project_name, created=True)


def _build_sample_payload(
    values: dict[str, Any],
    *,
    project_nr: int,
    importable: Any,
    field_targets: dict[str, str],
    field_widths: dict[str, int | None],
    lookup_allowed: dict[str, dict[str, str]],
    sanitizer: Any,
) -> dict[str, Any]:
    """One `sample_t` row from the reviewed values, vocabularies enforced."""
    sample_payload: dict[str, Any] = {
        "project_nr": project_nr,
        "editable": DEFAULT_SAMPLE_EDITABLE,
        "not_tobedated": DEFAULT_SAMPLE_NOT_TOBEDATED,
        # The lookup columns are NOT NULL-friendly in the legacy schema and
        # the UI renders "undefined" as an empty dash, so default rather
        # than leave NULL.
        "type": DEFAULT_LOOKUP_VALUE,
        "material": DEFAULT_LOOKUP_VALUE,
        "fraction": DEFAULT_LOOKUP_VALUE,
    }
    for field_name, raw in values.items():
        # Prep steps are not sample_t columns; they go on the preparation.
        if field_name in PREP_STEP_FIELDS or field_name not in importable:
            continue
        # A custom field may write to a differently-named column.
        target_column = field_targets.get(field_name, field_name)
        if target_column == "weight":
            try:
                sample_payload["weight"] = float(raw) if raw not in (None, "") else None
            except (TypeError, ValueError):
                sample_payload["weight"] = None
            continue
        if target_column == "sampling_date":
            parsed_date = _parse_iso_date(raw)
            if parsed_date is not None:
                sample_payload["sampling_date"] = parsed_date
            continue
        if field_name in lookup_allowed:
            # Controlled vocabulary: accept only a known entry.
            match = lookup_allowed[field_name].get(str(raw).strip().lower())
            sample_payload[target_column] = match or DEFAULT_LOOKUP_VALUE
            continue
        width = _SAMPLE_WIDTHS.get(target_column, field_widths.get(field_name))
        cleaned = _clean(raw, max_length=width)
        if cleaned is None:
            continue
        if target_column in ("user_label", "user_label_nr", "user_desc1", "user_desc2"):
            cleaned = _clean(sanitizer.replace_bad_characters(cleaned), max_length=width)
        sample_payload[target_column] = cleaned
    return sample_payload


def _create_samples(
    repo: Any,
    session: Any,
    rows: list[tuple[int, dict[str, Any]]],
    *,
    project_nr: int,
    registry: Any,
    sanitizer: Any,
) -> tuple[list[int], list[str]]:
    """One sample per row, each with preparation #1 (carrying the prep
    steps) and target #1, so the bench screens have something to write into.

    Vocabularies are loaded once and indexed case-insensitively; anything
    not in a list is replaced by "undefined" rather than written through —
    the review UI already offered a chance to map it, and stray free text
    would pollute a column the whole app treats as an enum. The registry
    knows which fields exist and which are lookup-backed, including any
    the operator defined in Setup.
    """
    importable = registry.importable if registry else IMPORTABLE_SAMPLE_FIELDS
    field_targets = {k: f.target for k, f in registry.fields.items()} if registry else {}
    field_widths = {k: f.max_length for k, f in registry.fields.items()} if registry else {}
    lookup_getters = registry.lookup_fields if registry else _LOOKUP_FIELD_GETTERS
    lookup_allowed = {
        field_name: {str(o).strip().lower(): str(o) for o in getattr(repo, getter)()}
        for field_name, getter in lookup_getters.items()
    }
    allowed_methods = {str(o).strip().lower(): str(o) for o in repo.get_methods()}

    sample_nrs: list[int] = []
    sample_labels: list[str] = []
    for _row_number, values in rows:
        sample_payload = _build_sample_payload(
            values,
            project_nr=project_nr,
            importable=importable,
            field_targets=field_targets,
            field_widths=field_widths,
            lookup_allowed=lookup_allowed,
            sanitizer=sanitizer,
        )
        sample = repo.create_sample(sample_payload)
        session.flush()
        sample_nr = int(sample.sample_nr)
        sample_labels.append(str(sample_payload.get("user_label") or ""))

        prep = repo.create_blank_prep(sample_nr=sample_nr, prep_nr=1)
        steps_written = False
        for step_field in PREP_STEP_FIELDS:
            method = _lookup_or_default(values.get(step_field), allowed_methods, default=None)
            if method:
                setattr(prep, step_field, method)
                steps_written = True
        if steps_written:
            session.flush()
        repo.create_blank_target(sample_nr=sample_nr, prep_nr=1, target_nr=1)
        sample_nrs.append(sample_nr)
    return sample_nrs, sample_labels


def commit_import(
    service: Any,
    payload: dict[str, Any],
    *,
    today: date | None = None,
    registry: Any = None,
) -> ImportResult:
    """Create submitter / project / samples from an approved payload.

    `payload` is the reviewed draft posted back by the wizard:

        {
          "submitter": {"user_nr": 123 | null, "values": {...}},
          "invoice":   {"user_nr": 456 | null, "values": {...}, "enabled": bool},
          "project":   {"project": "...", "in_date": "...", "desired_date": "...",
                        "project_comment": "...", "priority": 1, "price": "300"},
          "samples":   [{"include": true, "row_number": 36, "values": {...}}, ...]
        }

    A `user_nr` on submitter/invoice means "reuse this existing record";
    null means "create a new one from `values`".

    The five steps each flush; the single `commit()` at the end means an
    exception anywhere rolls the whole import back.
    """
    from sams_web.services import TextSanitizer

    today = today or date.today()
    repo, session = service.repo, service.session

    plan = _validate_payload(payload)
    submitter = _resolve_submitter(repo, session, payload, TextSanitizer)
    invoice = _resolve_invoice(repo, session, payload, TextSanitizer)
    project = _resolve_project(
        repo,
        session,
        payload,
        project_name=plan.project_name,
        user_nr=submitter.user_nr,
        invoice_nr=invoice.user_nr if invoice else None,
        today=today,
        sanitizer=TextSanitizer,
    )
    sample_nrs, sample_labels = _create_samples(
        repo, session, plan.rows, project_nr=project.project_nr, registry=registry, sanitizer=TextSanitizer
    )
    session.commit()

    return ImportResult(
        project_nr=project.project_nr,
        project_name=project.name,
        user_nr=submitter.user_nr,
        submitter_created=submitter.created,
        submitter_name=submitter.name,
        invoice_nr=invoice.user_nr if invoice else None,
        invoice_created=bool(invoice and invoice.created),
        project_created=project.created,
        sample_nrs=sample_nrs,
        sample_labels=sample_labels,
        skipped_rows=plan.skipped_rows,
    )


__all__ = [
    "DEFAULT_LOOKUP_VALUE",
    "DEFAULT_PROJECT_PRICE",
    "DEFAULT_PROJECT_PRIORITY",
    "DEFAULT_PROJECT_STATUS",
    "DEFAULT_TURNAROUND_DAYS",
    "ImportCommitError",
    "ImportResult",
    "commit_import",
]

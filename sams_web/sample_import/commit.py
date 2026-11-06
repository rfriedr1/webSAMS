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
from datetime import date, datetime, timedelta
from typing import Any

from sams_web.sample_import.fields import KIND_DATE, KIND_INTEGER, NUMERIC_KINDS, FieldRegistry

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


# Contact column widths taken from the live MySQL schema via
# `information_schema.COLUMNS`. Sample widths are not listed here: they come
# from the field registry, i.e. from `models.Sample`, which mirrors the live
# `sample_t` exactly (the server is in strict mode, so too wide a value fails
# the INSERT).
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

_PROJECT_WIDTHS: dict[str, int] = {
    "project": 100,
    "price": 20,
    "order_nr": 60,
}

#: Sample columns whose text gets the app's bad-character guard.
_SANITIZED_SAMPLE_COLUMNS = frozenset({"user_label", "user_label_nr", "user_desc1", "user_desc2"})


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


def _index_choices(options: Any) -> dict[str, str]:
    """A lookup list keyed case-insensitively: `"Bone " -> "bone"` style matching."""
    return {str(o).strip().lower(): str(o) for o in options}


def _coerce_number(raw: Any, kind: str) -> tuple[float | int | None, str | None]:
    """Reviewed value -> number for a numeric column, as `(value, error)`.

    Empty is `None` (no error). A decimal comma is accepted (`"12,5"`).
    Anything else that does not read as a number is an error, so the
    operator fixes it in the review table rather than MySQL rejecting the
    whole import (strict mode) — or the value being dropped silently.
    """
    if raw is None:
        return None, None
    if isinstance(raw, bool):
        return int(raw), None
    if isinstance(raw, (int, float)):
        number: float = float(raw)
    else:
        text = str(raw).strip()
        if not text:
            return None, None
        try:
            number = float(text.replace(",", "."))
        except ValueError:
            return None, f"{text!r} is not a number"
    if kind == KIND_INTEGER:
        if not number.is_integer():
            return None, f"{raw!r} is not a whole number"
        return int(number), None
    return number, None


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


#: The legacy tables are `latin1` (MySQL's cp1252). Anything outside it — Cyrillic,
#: Greek, CJK, many typographic symbols — makes MySQL refuse the whole INSERT
#: (error 1366), which used to surface as a bare 500 halfway through the import.
DB_TEXT_ENCODING = "cp1252"


def unsupported_characters(value: Any) -> str:
    """The characters of `value` the database's text columns cannot store."""
    if not isinstance(value, str):
        return ""
    bad: list[str] = []
    for ch in value:
        try:
            ch.encode(DB_TEXT_ENCODING)
        except UnicodeEncodeError:
            if ch not in bad:
                bad.append(ch)
    return "".join(bad)


def _check_storable(where: str, values: dict[str, Any]) -> None:
    for key, value in values.items():
        bad = unsupported_characters(value)
        if bad:
            raise ImportCommitError(
                f"{where}, field '{key}': the database cannot store the character(s) "
                f"{' '.join(repr(c)[1:-1] for c in bad)} in \"{str(value)[:60]}\" "
                "(its text columns are Latin-1, so Cyrillic, Greek and similar scripts "
                "are not possible). Replace them with Latin letters — e.g. a transliteration — "
                "in the review table, or exclude the row."
            )


def _check_numbers(where: str, values: dict[str, Any], registry: FieldRegistry) -> None:
    for key, raw in values.items():
        field_def = registry.fields.get(key)
        if field_def is None or field_def.kind not in NUMERIC_KINDS:
            continue
        _, error = _coerce_number(raw, field_def.kind)
        if error:
            raise ImportCommitError(
                f"{where}, field '{field_def.label}': {error}. "
                "Correct it in the review table, or exclude the row."
            )


def _validate_payload(payload: dict[str, Any], registry: FieldRegistry) -> _ImportPlan:
    """Reject anything that would fail part-way; nothing is written yet."""
    project_input = payload.get("project") or {}
    project_name = _clean(project_input.get("project"), max_length=_PROJECT_WIDTHS["project"])
    if not project_name:
        raise ImportCommitError("A project name is required.")

    _check_storable("Project", project_input)
    _check_storable("Submitter", (payload.get("submitter") or {}).get("values") or {})
    if (payload.get("invoice") or {}).get("enabled"):
        _check_storable("Invoice recipient", (payload.get("invoice") or {}).get("values") or {})

    all_rows = payload.get("samples") or []
    rows = [r for r in all_rows if r.get("include", True)]
    if not rows:
        raise ImportCommitError("No samples were selected for import.")

    prepared: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        values = row.get("values") or {}
        where = f"Row {row.get('row_number', '?')}"
        if not _clean(values.get("user_label")):
            raise ImportCommitError(f"{where} has no sample name. Fix or exclude it before importing.")
        _check_storable(where, values)
        _check_numbers(where, values, registry)
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
        field_name: _index_choices(getattr(repo, getter)())
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
            # Mapped columns are INSERTed as NULL when unset, overriding the DB
            # default of 0; the legacy tools expect 0 ("not returned yet").
            "returned_to_sender": 0,
            "prep_returned_to_sender": 0,
        }
    )
    session.flush()
    return _ProjectRef(int(project.project_nr), project_name, created=True)


def _build_sample_payload(
    values: dict[str, Any],
    *,
    project_nr: int,
    registry: FieldRegistry,
    lookup_allowed: dict[str, dict[str, str]],
    sanitizer: Any,
) -> dict[str, Any]:
    """One `sample_t` row from the reviewed values, vocabularies enforced.

    Each value is converted by its registry field's kind and clamped to its
    column width, both taken from `models.Sample`. Numbers were checked by
    `_validate_payload` already, so an unreadable one cannot reach here.
    """
    sample_payload: dict[str, Any] = {
        "project_nr": project_nr,
        "editable": DEFAULT_SAMPLE_EDITABLE,
        "not_tobedated": DEFAULT_SAMPLE_NOT_TOBEDATED,
        # Legacy flags: write 0 explicitly (an unset mapped column is INSERTed
        # as NULL, which would override the DB default).
        "s_no_leftover": 0,
        "c_n_isotop_a": 0,
        "c_n_isotop_a_moved": 0,
        # The lookup columns are NOT NULL-friendly in the legacy schema and
        # the UI renders "undefined" as an empty dash, so default rather
        # than leave NULL.
        "type": DEFAULT_LOOKUP_VALUE,
        "material": DEFAULT_LOOKUP_VALUE,
        "fraction": DEFAULT_LOOKUP_VALUE,
    }
    for field_name, raw in values.items():
        field_def = registry.fields.get(field_name)
        # Prep steps are not sample_t columns; they go on the preparation.
        # Extra-analysis flags are handled below.
        if field_def is None or field_name in PREP_STEP_FIELDS:
            continue
        # A custom field may write to a differently-named column.
        column = field_def.target
        if field_def.kind in NUMERIC_KINDS:
            number, _ = _coerce_number(raw, field_def.kind)
            if number is not None:
                sample_payload[column] = number
            continue
        if field_def.kind == KIND_DATE:
            parsed_date = _parse_iso_date(raw)
            if parsed_date is not None:
                sample_payload[column] = parsed_date
            continue
        if field_name in lookup_allowed:
            # Controlled vocabulary: accept only a known entry.
            match = lookup_allowed[field_name].get(str(raw).strip().lower())
            sample_payload[column] = match or DEFAULT_LOOKUP_VALUE
            continue
        cleaned = _clean(raw, max_length=field_def.max_length)
        if cleaned is None:
            continue
        if column in _SANITIZED_SAMPLE_COLUMNS:
            cleaned = _clean(sanitizer.replace_bad_characters(cleaned), max_length=field_def.max_length)
        sample_payload[column] = cleaned
    # Extra analyses come from the wizard's own step, never from a sheet
    # column, so they are applied last and coerced to the legacy 0/1.
    sample_payload["c_n_isotop_a"] = _flag(values.get("cn_isotop_a"))
    sample_payload["dendro_a"] = _flag(values.get("dendro_a"))
    return sample_payload


def _flag(raw: Any) -> int:
    """Wizard checkbox value -> legacy 0/1 flag (anything unclear is 0)."""
    if isinstance(raw, str):
        return 1 if raw.strip().lower() in ("1", "true", "yes", "on") else 0
    return 1 if raw else 0


#: `method_t` entry meaning "this sample gets no pretreatment".
NO_PREPARATION_METHOD = "none"


def needs_no_preparation(step_methods: list[str | None]) -> bool:
    """True when prep step 1 is "none" and no later step names a real method.

    Such a sample has nothing to do at the preparation bench, so the import
    closes its preparation straight away (`prep_end` = today) and it lands
    in *Waiting for Graph* instead of *Planned*. A "none" in step 1 followed
    by a real method in steps 2-5 still counts as preparation.
    """
    normalized = [str(m or "").strip().lower() for m in step_methods]
    if not normalized or normalized[0] != NO_PREPARATION_METHOD:
        return False
    return all(m in ("", NO_PREPARATION_METHOD) for m in normalized[1:])


def _create_samples(
    repo: Any,
    session: Any,
    rows: list[tuple[int, dict[str, Any]]],
    *,
    project_nr: int,
    today: date,
    registry: FieldRegistry,
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
    lookup_allowed = {
        field_name: _index_choices(getattr(repo, getter)())
        for field_name, getter in registry.lookup_fields.items()
    }
    allowed_methods = _index_choices(repo.get_methods())

    sample_nrs: list[int] = []
    sample_labels: list[str] = []
    for row_number, values in rows:
        try:
            sample_payload = _build_sample_payload(
                values,
                project_nr=project_nr,
                registry=registry,
                lookup_allowed=lookup_allowed,
                sanitizer=sanitizer,
            )
            sample = repo.create_sample(sample_payload)
            session.flush()
            sample_nr = int(sample.sample_nr)
            sample_labels.append(str(sample_payload.get("user_label") or ""))

            prep = repo.create_blank_prep(sample_nr=sample_nr, prep_nr=1)
            step_methods: list[str | None] = []
            for step_field in PREP_STEP_FIELDS:
                method = _lookup_or_default(values.get(step_field), allowed_methods, default=None)
                step_methods.append(method)
                if method:
                    setattr(prep, step_field, method)
            if needs_no_preparation(step_methods):
                # Midnight, like the bench's own auto-stamp (`_autostamp_prep_dates`).
                prep.prep_end = datetime.combine(today, datetime.min.time())
            if any(step_methods):
                session.flush()
            repo.create_blank_target(sample_nr=sample_nr, prep_nr=1, target_nr=1)
            sample_nrs.append(sample_nr)
        except Exception as exc:
            exc.import_row = (row_number, str(values.get("user_label") or ""))  # type: ignore[attr-defined]
            raise
    return sample_nrs, sample_labels


def commit_import(
    service: Any,
    payload: dict[str, Any],
    *,
    registry: FieldRegistry,
    today: date | None = None,
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

    plan = _validate_payload(payload, registry)
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
        repo,
        session,
        plan.rows,
        project_nr=project.project_nr,
        today=today,
        registry=registry,
        sanitizer=TextSanitizer,
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
    "NO_PREPARATION_METHOD",
    "needs_no_preparation",
    "ImportResult",
    "commit_import",
]

"""Operator-editable import settings, persisted in `setup_data.json`.

Two Setup sections live here:

- **Import Column Headings** (`import_column_headings`) — extra spellings
  per sample field, merged over the built-in vocabulary at parse time.
  Teaching the importer "Probenkennung" once means every future sheet
  from that customer is recognised automatically.

- **E-mail** (`email_settings`) — SMTP connection details plus one or
  more named confirmation templates. Templates are keyed by language so
  a German submitter gets the German text.

Both follow the same pattern as `lab_warning_thresholds.py`: the code is
the source of truth for the *shape*, the JSON file holds the values, and
the Setup page renders whatever the code declares.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from sams_web.sample_import.fields import SAMPLE_TARGET_COLUMNS, available_targets
from sams_web.sample_import.vocabulary import SAMPLE_COLUMN_SYNONYMS, SAMPLE_FIELD_LABELS
from sams_web.setup_store import SetupStore

SETUP_SECTION_IMPORT_HEADINGS = "import_column_headings"
SETUP_SECTION_EMAIL = "email_settings"


# --- Import column headings ------------------------------------------------


class ImportHeadingStore:
    """Operator-defined import vocabulary.

    Persisted shape::

        {
          "headings": {"user_label": ["Probenkennung", ...], ...},
          "custom":   [{"target": "pre_sub_treat",
                        "label":  "Customer pre-treatment",
                        "headings": ["Vorbehandlung Kunde"]}]
        }

    `headings` teaches extra spellings for the built-in fields.
    `custom` defines whole new import columns, each pointing at a real
    writable `sample_t` column — so the lab can start collecting a new
    piece of information without a code change, and still cannot invent
    a place to put it.

    An older flat `{field: [...]}` file is still read correctly.
    """

    def __init__(
        self, setup_store: SetupStore, section_key: str = SETUP_SECTION_IMPORT_HEADINGS
    ) -> None:
        self.setup_store = setup_store
        self.section_key = section_key

    # -- read -----------------------------------------------------------

    def _raw(self) -> dict[str, Any]:
        raw = self.setup_store.get_section(self.section_key, default=None)
        if not isinstance(raw, dict):
            return {}
        # Backwards compatibility with the first release, which stored a
        # flat {field: [heading, ...]} mapping and no custom fields.
        if "headings" not in raw and "custom" not in raw:
            return {"headings": raw, "custom": []}
        return raw

    @staticmethod
    def _clean_list(values: Any) -> list[str]:
        if isinstance(values, str):
            items = values.splitlines()
        elif isinstance(values, list):
            items = [str(v) for v in values]
        else:
            return []
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in items:
            text = str(item).strip()
            key = text.lower()
            if text and key not in seen:
                seen.add(key)
                cleaned.append(text)
        return cleaned

    def load_headings(self) -> dict[str, list[str]]:
        """Extra spellings for the built-in fields."""
        raw = self._raw().get("headings")
        if not isinstance(raw, dict):
            return {}
        return {
            field_name: self._clean_list(raw.get(field_name))
            for field_name in SAMPLE_COLUMN_SYNONYMS
            if self._clean_list(raw.get(field_name))
        }

    def load_custom_fields(self) -> list[dict[str, Any]]:
        """Operator-defined import columns."""
        raw = self._raw().get("custom")
        if not isinstance(raw, list):
            return []
        fields: list[dict[str, Any]] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            target = str(entry.get("target") or "").strip()
            headings = self._clean_list(entry.get("headings"))
            if not target or target not in SAMPLE_TARGET_COLUMNS or not headings:
                continue
            fields.append(
                {
                    "target": target,
                    "label": str(entry.get("label") or SAMPLE_TARGET_COLUMNS[target].label),
                    "headings": headings,
                }
            )
        return fields

    # Kept for callers that only want the built-in overrides.
    def load(self) -> dict[str, list[str]]:
        return self.load_headings()

    def registry(self) -> Any:
        """The resolved `FieldRegistry` for this configuration."""
        from sams_web.sample_import.fields import build_registry

        return build_registry(
            custom_fields=self.load_custom_fields(),
            extra_headings=self.load_headings(),
        )

    # -- write ----------------------------------------------------------

    def save(self, headings: Mapping[str, list[str]], custom: list[dict[str, Any]]) -> None:
        self.setup_store.set_section(
            self.section_key,
            {
                "headings": {k: list(v) for k, v in headings.items() if v},
                "custom": custom,
            },
        )

    def update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """Apply the Setup form.

        Built-in rows arrive as one newline-separated textarea each.
        Custom rows arrive as parallel `custom_target[]` / `custom_label[]`
        / `custom_headings[]` lists; a row with no target or no headings
        is treated as deleted.
        """
        headings: dict[str, list[str]] = {}
        for field_name in SAMPLE_COLUMN_SYNONYMS:
            cleaned = self._clean_list(payload.get(field_name))
            if cleaned:
                headings[field_name] = cleaned

        targets = payload.get("custom_target") or []
        labels = payload.get("custom_label") or []
        heading_blocks = payload.get("custom_headings") or []
        if isinstance(targets, str):
            targets, labels, heading_blocks = [targets], [labels], [heading_blocks]

        custom: list[dict[str, Any]] = []
        seen_targets: set[str] = set()
        for index, target in enumerate(targets):
            name = str(target or "").strip()
            if not name or name in seen_targets:
                continue
            if name not in SAMPLE_TARGET_COLUMNS:
                raise ValueError(f"{name!r} is not a column an import can write to.")
            block = heading_blocks[index] if index < len(heading_blocks) else ""
            cleaned = self._clean_list(block)
            if not cleaned:
                continue
            seen_targets.add(name)
            label = str(labels[index] if index < len(labels) else "").strip()
            custom.append(
                {
                    "target": name,
                    "label": label or SAMPLE_TARGET_COLUMNS[name].label,
                    "headings": cleaned,
                }
            )

        self.save(headings, custom)
        return {"headings": headings, "custom": custom}

    # -- editor view ----------------------------------------------------

    def rows_for_editor(self) -> list[dict[str, Any]]:
        """Built-in fields: label, recognised headings, operator extras."""
        stored = self.load_headings()
        return [
            {
                "key": field_name,
                "label": SAMPLE_FIELD_LABELS.get(field_name, field_name),
                "builtin": list(SAMPLE_COLUMN_SYNONYMS[field_name]),
                "custom": stored.get(field_name, []),
                "custom_text": "\n".join(stored.get(field_name, [])),
            }
            for field_name in SAMPLE_COLUMN_SYNONYMS
        ]

    def custom_rows_for_editor(self) -> list[dict[str, Any]]:
        return [
            {**entry, "headings_text": "\n".join(entry["headings"])}
            for entry in self.load_custom_fields()
        ]


# --- E-mail settings -------------------------------------------------------


@dataclass(frozen=True)
class EmailField:
    key: str
    label: str
    description: str
    kind: str = "text"          # text | number | password | select | checkbox
    default: Any = ""
    options: tuple[str, ...] = ()


EMAIL_SERVER_FIELDS: tuple[EmailField, ...] = (
    EmailField("smtp_host", "SMTP server", "Hostname of the outgoing mail server.", default=""),
    EmailField("smtp_port", "Port", "Usually 587 for STARTTLS, 465 for SSL, 25 for plain.", kind="number", default=587),
    EmailField(
        "smtp_security",
        "Security",
        "STARTTLS is the common choice for port 587.",
        kind="select",
        default="starttls",
        options=("starttls", "ssl", "none"),
    ),
    EmailField("smtp_user", "Username", "Leave empty if the server does not require authentication.", default=""),
    EmailField("smtp_password", "Password", "Stored in the setup file in plain text — use a dedicated mailbox account.", kind="password", default=""),
    EmailField("from_address", "From address", "Appears as the sender of confirmation e-mails.", default=""),
    EmailField("from_name", "From name", "Display name shown next to the sender address.", default="CEZA C14 Laboratory"),
    EmailField("reply_to", "Reply-to", "Optional. Where customer replies should go.", default=""),
    EmailField("bcc", "BCC", "Optional. Copies every confirmation to this address for the lab's records.", default=""),
)

#: Placeholders available inside a template's subject and body.
EMAIL_PLACEHOLDERS: tuple[tuple[str, str], ...] = (
    ("{submitter_name}", "Submitter's name, e.g. “Picin, Andrea”"),
    ("{submitter_first_name}", "Submitter's first name"),
    ("{submitter_last_name}", "Submitter's last name"),
    ("{salutation}", "Salutation from the submitter record"),
    ("{project_nr}", "Created project number"),
    ("{project_name}", "Project name"),
    ("{sample_count}", "Number of samples created"),
    ("{sample_list}", "One line per sample: lab number and the submitter's own label"),
    ("{lab_name}", "The From name configured above"),
)

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "language": "en",
        "label": "English",
        "subject": "CEZA C14 — your samples have been received (project {project_nr})",
        "body": (
            "Dear {submitter_name},\n\n"
            "thank you for your submission. We have received {sample_count} sample(s) "
            "for project {project_nr} “{project_name}” and registered them under the "
            "following laboratory numbers:\n\n"
            "{sample_list}\n\n"
            "Please quote these laboratory numbers in any correspondence about this "
            "submission. We will contact you once the measurements are complete.\n\n"
            "Kind regards,\n"
            "{lab_name}\n"
        ),
    },
    "de": {
        "language": "de",
        "label": "German",
        "subject": "CEZA C14 — Eingang Ihrer Proben (Projekt {project_nr})",
        "body": (
            "Sehr geehrte/r {submitter_name},\n\n"
            "vielen Dank für Ihre Einsendung. Wir haben {sample_count} Probe(n) für das "
            "Projekt {project_nr} „{project_name}“ erhalten und unter den folgenden "
            "Labornummern registriert:\n\n"
            "{sample_list}\n\n"
            "Bitte geben Sie diese Labornummern bei Rückfragen zu dieser Einsendung an. "
            "Wir melden uns, sobald die Messungen abgeschlossen sind.\n\n"
            "Mit freundlichen Grüßen\n"
            "{lab_name}\n"
        ),
    },
}


def default_email_settings() -> dict[str, Any]:
    return {
        **{f.key: f.default for f in EMAIL_SERVER_FIELDS},
        "templates": {code: dict(tpl) for code, tpl in DEFAULT_TEMPLATES.items()},
    }


#: The fields that identify *where* a stored SMTP password is sent. If any
#: of them differs from what is saved, the stored password belongs to a
#: different connection and must not be reused.
SMTP_IDENTITY_FIELDS: tuple[str, ...] = ("smtp_host", "smtp_port", "smtp_security", "smtp_user")


def _identity_value(settings: Mapping[str, Any], key: str) -> str:
    return str(settings.get(key) if settings.get(key) is not None else "").strip().lower()


def stored_password_applies(candidate: Mapping[str, Any], saved: Mapping[str, Any]) -> bool:
    """True when `candidate` targets exactly the saved SMTP connection.

    Guards every place a blank password box means "reuse the stored one":
    the secret may only ever be presented to the server it was saved for.
    """
    return all(
        _identity_value(candidate, key) == _identity_value(saved, key)
        for key in SMTP_IDENTITY_FIELDS
    )


class EmailSettingsStore:
    """SMTP connection settings + confirmation templates."""

    def __init__(self, setup_store: SetupStore, section_key: str = SETUP_SECTION_EMAIL) -> None:
        self.setup_store = setup_store
        self.section_key = section_key

    def load(self) -> dict[str, Any]:
        defaults = default_email_settings()
        raw = self.setup_store.get_section(self.section_key, default=None)
        if not isinstance(raw, dict):
            return defaults

        settings: dict[str, Any] = {}
        for f in EMAIL_SERVER_FIELDS:
            value = raw.get(f.key, f.default)
            if f.kind == "number":
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    value = f.default
            elif f.kind == "select" and value not in f.options:
                value = f.default
            else:
                value = "" if value is None else str(value)
            settings[f.key] = value

        templates = raw.get("templates")
        merged = {code: dict(tpl) for code, tpl in DEFAULT_TEMPLATES.items()}
        if isinstance(templates, dict):
            for code, tpl in templates.items():
                if not isinstance(tpl, dict):
                    continue
                base = merged.get(str(code), {"language": str(code), "label": str(code)})
                merged[str(code)] = {
                    "language": str(code),
                    "label": str(tpl.get("label") or base.get("label") or code),
                    "subject": str(tpl.get("subject") or base.get("subject", "")),
                    "body": str(tpl.get("body") or base.get("body", "")),
                }
        settings["templates"] = merged
        return settings

    def save(self, values: Mapping[str, Any]) -> None:
        self.setup_store.set_section(self.section_key, dict(values))

    def update(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        current = self.load()
        updated: dict[str, Any] = {}
        for f in EMAIL_SERVER_FIELDS:
            raw = payload.get(f.key, current.get(f.key, f.default))
            if f.kind == "number":
                try:
                    updated[f.key] = int(str(raw).strip() or f.default)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"'{f.label}' must be a whole number.") from exc
            elif f.kind == "select":
                value = str(raw).strip() or str(f.default)
                if value not in f.options:
                    raise ValueError(
                        f"'{f.label}' must be one of: {', '.join(f.options)}."
                    )
                updated[f.key] = value
            elif f.kind == "password":
                # The form never renders the stored secret, so an empty
                # box means "unchanged" — resolved below, once the other
                # connection fields are known.
                updated[f.key] = str(raw or "").strip()
            else:
                updated[f.key] = str(raw or "").strip()

        # Keep the stored password only if the connection target is
        # unchanged. Saving a new host with a blank password box would
        # otherwise hand the old mailbox password to the new server on
        # the next send.
        if not updated.get("smtp_password") and stored_password_applies(updated, current):
            updated["smtp_password"] = str(current.get("smtp_password") or "")

        templates = dict(current.get("templates") or {})
        for code in list(templates):
            subject = payload.get(f"template_{code}_subject")
            body = payload.get(f"template_{code}_body")
            if subject is not None:
                templates[code]["subject"] = str(subject)
            if body is not None:
                templates[code]["body"] = str(body)
        updated["templates"] = templates
        self.save(updated)
        return updated

    def is_configured(self) -> bool:
        """True when enough is set to attempt a send."""
        settings = self.load()
        return bool(settings.get("smtp_host") and settings.get("from_address"))

    def template_for_language(self, language: str | None) -> dict[str, str]:
        """Pick a template by language code, falling back to English."""
        settings = self.load()
        templates: dict[str, Any] = settings.get("templates") or {}
        code = (language or "").strip().lower()[:2]
        if code and code in templates:
            return templates[code]
        if "en" in templates:
            return templates["en"]
        return next(iter(templates.values()), {"subject": "", "body": ""})


__all__ = [
    "DEFAULT_TEMPLATES",
    "EMAIL_PLACEHOLDERS",
    "EMAIL_SERVER_FIELDS",
    "SETUP_SECTION_EMAIL",
    "SETUP_SECTION_IMPORT_HEADINGS",
    "EmailField",
    "EmailSettingsStore",
    "ImportHeadingStore",
    "available_targets",
    "default_email_settings",
]

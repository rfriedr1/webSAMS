"""One handler per Setup section.

Each Setup section used to be spread over four `if section == …` chains:
building the page context (`services.get_setup_section`), saving
(`services.update_setup_section`), reading the posted form (the Setup
router) and choosing the editor (`setup.html`). A handler now owns the first
three, and the editor is `templates/setup/_<kind>.html`.

Adding a section: a `SetupSection` entry in `setup_sections.py`, a handler
here registered in `SETUP_HANDLERS`, and one template part.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Mapping

from sams_web.import_settings import (
    EMAIL_PLACEHOLDERS,
    EMAIL_SERVER_FIELDS,
    EmailSettingsStore,
    ImportHeadingStore,
    available_targets,
)
from sams_web.ea_checks import ELEMENTS, EaCheckSettingsStore
from sams_web.lab_staff import LabStaffStore
from sams_web.lab_warning_thresholds import LAB_WARNING_THRESHOLD_FIELDS
from sams_web.sample_import.vocabulary import SAMPLE_COLUMN_SYNONYMS
from sams_web.sample_photos import SamplePhotoSettingsStore
from sams_web.setup_sections import (
    SETUP_SECTION_EA_CHECKS,
    SETUP_SECTION_EMAIL,
    SETUP_SECTION_LAB_STAFF,
    SETUP_SECTION_GRAPHITIZATION_SYSTEMS,
    SETUP_SECTION_IMPORT_HEADINGS,
    SETUP_SECTION_LAB_WARNING_THRESHOLDS,
    SETUP_SECTION_SAMPLE_PHOTOS,
    SETUP_SECTION_STANDARD_THRESHOLDS,
)
from sams_web.thresholds import STANDARD_LABELS, THRESHOLD_FIELDS

if TYPE_CHECKING:  # pragma: no cover
    from sams_web.services import SamsService

GRAPHITIZATION_SYSTEM_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


class SetupSectionHandler:
    """How one Setup section is shown, read from its form, and saved.

    `kind` names the editor template (`setup/_<kind>.html`) and is exposed
    as `active_section.kind`.
    """

    kind: str = "placeholder"

    def context(self, service: "SamsService") -> dict[str, Any]:
        """Section-specific values for the editor."""
        return {}

    def read_form(self, form: Any) -> dict[str, Any]:
        """Turn the posted form into the payload `save` accepts."""
        return {}

    def save(self, service: "SamsService", payload: Mapping[str, Any]) -> None:
        """Validate and persist; raise `ValueError` with a message to show."""
        raise ValueError("No update handler configured for this setup section.")

    def keep_typed(self, context: dict[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
        """After a rejected save, put what the operator typed back into the
        editor so it can be corrected rather than retyped."""
        return context


def build_threshold_rows(payload: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, key in STANDARD_LABELS:
        values = payload.get(key, {})
        rows.append(
            {
                "label": label,
                "key": key,
                "red_below": values.get("red_below", ""),
                "yellow_min": values.get("yellow_min", ""),
                "yellow_max": values.get("yellow_max", ""),
                "green_above": values.get("green_above", ""),
            }
        )
    return rows


class StandardThresholdsHandler(SetupSectionHandler):
    kind = "threshold_matrix"

    def context(self, service):
        thresholds = service.get_standard_thresholds()
        return {
            "storage_section": service.threshold_store.section_key,
            "thresholds": thresholds,
            "threshold_fields": THRESHOLD_FIELDS,
            "threshold_rows": build_threshold_rows(thresholds),
        }

    def read_form(self, form):
        return {
            key: {field: form.get(f"{key}_{field}") for field, _ in THRESHOLD_FIELDS}
            for _, key in STANDARD_LABELS
        }

    def save(self, service, payload):
        service.update_standard_thresholds(dict(payload))

    def keep_typed(self, context, payload):
        if payload:
            context["threshold_rows"] = build_threshold_rows(payload)
        return context


class GraphitizationSystemsHandler(SetupSectionHandler):
    kind = "string_list"

    def context(self, service):
        systems = service.get_graphitization_systems()
        return {
            "storage_section": SETUP_SECTION_GRAPHITIZATION_SYSTEMS,
            "list_items": systems,
            "list_text": "\n".join(systems),
            "list_label": "Systems",
            "list_placeholder": "One system per line (e.g. mag)",
            "list_help": "Used as the suffix in graph batch names: graph_YYMMDD_system",
        }

    def read_form(self, form):
        raw = str(form.get("graphitization_systems_text") or "")
        return {"items": raw.splitlines(), "raw_text": raw}

    def save(self, service, payload):
        items = payload.get("items")
        if not isinstance(items, list):
            raise ValueError("Graphitization systems payload must contain a list of items.")
        cleaned: list[str] = []
        seen: set[str] = set()
        for index, item in enumerate(items, start=1):
            if not isinstance(item, str):
                raise ValueError(f"System entry {index} must be text.")
            value = item.strip()
            if value == "":
                continue
            if not GRAPHITIZATION_SYSTEM_VALUE_PATTERN.fullmatch(value):
                raise ValueError(
                    f"Invalid system '{value}'. Use only letters, numbers, dot, dash, and underscore."
                )
            if value in seen:
                raise ValueError(f"Duplicate system '{value}' is not allowed.")
            cleaned.append(value)
            seen.add(value)
        if not cleaned:
            raise ValueError("At least one graphitization system is required.")
        service.setup_store.set_section(SETUP_SECTION_GRAPHITIZATION_SYSTEMS, cleaned)

    def keep_typed(self, context, payload):
        if payload.get("raw_text"):
            context["list_text"] = str(payload["raw_text"])
        return context


class LabWarningThresholdsHandler(SetupSectionHandler):
    kind = "numeric_thresholds"

    def context(self, service):
        values = service.get_lab_warning_thresholds()
        return {
            "storage_section": service.lab_warning_threshold_store.section_key,
            "numeric_threshold_rows": [
                {
                    "key": field.key,
                    "label": field.label,
                    "description": field.description,
                    "unit": field.unit,
                    "step": field.step,
                    "value": field.format(values.get(field.key, field.default)),
                }
                for field in LAB_WARNING_THRESHOLD_FIELDS
            ],
        }

    def read_form(self, form):
        return {field.key: form.get(field.key) for field in LAB_WARNING_THRESHOLD_FIELDS}

    def save(self, service, payload):
        service.update_lab_warning_thresholds(dict(payload))


class ImportHeadingsHandler(SetupSectionHandler):
    kind = "import_headings"

    def context(self, service):
        store = ImportHeadingStore(service.setup_store)
        custom_rows = store.custom_rows_for_editor()
        return {
            "storage_section": store.section_key,
            "heading_rows": store.rows_for_editor(),
            "custom_rows": custom_rows,
            "target_columns": available_targets({r["target"] for r in custom_rows}),
        }

    def read_form(self, form):
        # One newline-separated textarea per built-in sample field, plus any
        # number of operator-defined columns as three parallel lists.
        payload: dict[str, Any] = {
            field_name: form.get(f"heading_{field_name}", "") for field_name in SAMPLE_COLUMN_SYNONYMS
        }
        payload["custom_target"] = form.getlist("custom_target")
        payload["custom_label"] = form.getlist("custom_label")
        payload["custom_headings"] = form.getlist("custom_headings")
        return payload

    def save(self, service, payload):
        ImportHeadingStore(service.setup_store).update(payload)


class EmailSettingsHandler(SetupSectionHandler):
    kind = "email_settings"

    def context(self, service):
        store = EmailSettingsStore(service.setup_store)
        settings = store.load()
        return {
            "storage_section": store.section_key,
            "email_fields": [
                {
                    "key": f.key,
                    "label": f.label,
                    "description": f.description,
                    "kind": f.kind,
                    "options": list(f.options),
                    "value": settings.get(f.key, f.default),
                }
                for f in EMAIL_SERVER_FIELDS
            ],
            "email_templates": [
                {"code": code, **tpl} for code, tpl in sorted((settings.get("templates") or {}).items())
            ],
            "email_placeholders": [
                {"token": token, "description": desc} for token, desc in EMAIL_PLACEHOLDERS
            ],
            "email_configured": store.is_configured(),
        }

    def read_form(self, form):
        payload: dict[str, Any] = {field.key: form.get(field.key, "") for field in EMAIL_SERVER_FIELDS}
        # Template subject/body arrive as template_<lang>_subject/_body.
        for key in form.keys():
            if key.startswith("template_"):
                payload[key] = form.get(key, "")
        return payload

    def save(self, service, payload):
        EmailSettingsStore(service.setup_store).update(payload)


class SamplePhotosHandler(SetupSectionHandler):
    kind = "sample_photos"

    def context(self, service):
        store = SamplePhotoSettingsStore(service.setup_store)
        return {"storage_section": store.section_key, "folder": store.load()["folder"]}

    def read_form(self, form):
        return {"folder": str(form.get("folder") or "")}

    def save(self, service, payload):
        SamplePhotoSettingsStore(service.setup_store).update(payload)

    def keep_typed(self, context, payload):
        context["folder"] = payload.get("folder", "")
        return context


def _num_text(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


EA_STANDARD_FIELDS = ("std_key", "std_name", "std_lot") + tuple(
    f"std_{symbol}_{part}" for symbol, _ in ELEMENTS for part in ("ref", "min", "max", "step")
)
EA_INSTRUMENT_FIELDS = ("inst_key", "inst_label", "inst_systems", "inst_standards")


class EaChecksHandler(SetupSectionHandler):
    kind = "ea_checks"

    @staticmethod
    def _rows_from_raw(raw: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
        standards: list[dict[str, str]] = []
        for item in raw.get("standards") or []:
            if not isinstance(item, Mapping):
                continue
            row = {"std_key": str(item.get("key") or ""), "std_name": str(item.get("name") or ""),
                   "std_lot": str(item.get("lot") or "")}
            for symbol, _ in ELEMENTS:
                element = item.get(symbol) if isinstance(item.get(symbol), Mapping) else {}
                for part in ("ref", "min", "max", "step"):
                    row[f"std_{symbol}_{part}"] = _num_text(element.get(part))
            standards.append(row)
        instruments = [
            {
                "inst_key": str(item.get("key") or ""),
                "inst_label": str(item.get("label") or ""),
                "inst_systems": ", ".join(str(x) for x in item.get("systems") or []),
                "inst_standards": ", ".join(str(x) for x in item.get("standards") or []),
            }
            for item in raw.get("instruments") or []
            if isinstance(item, Mapping)
        ]
        return standards, instruments

    def context(self, service):
        store = EaCheckSettingsStore(service.setup_store)
        raw = store.raw()
        standards, instruments = self._rows_from_raw(raw)
        return {
            "storage_section": store.section_key,
            "ea_elements": ELEMENTS,
            "ea_standard_rows": standards,
            "ea_instrument_rows": instruments,
            "ea_reminder_days": raw.get("signoff_reminder_days", 31),
            "ea_system_options": service.get_graphitization_systems(),
        }

    def read_form(self, form):
        payload: dict[str, Any] = {name: form.getlist(name) for name in EA_STANDARD_FIELDS + EA_INSTRUMENT_FIELDS}
        payload["signoff_reminder_days"] = form.get("signoff_reminder_days", "")
        return payload

    def save(self, service, payload):
        store = EaCheckSettingsStore(service.setup_store)
        current = {s.key for s in store.load().standards}
        posted = {str(k or "").strip().lower() for k in payload.get("std_key") or []}
        # Only ask the database when a standard is actually being removed.
        in_use = service.ea_standards_in_use() if current - posted else set()
        store.update(payload, standards_in_use=in_use)

    def keep_typed(self, context, payload):
        def rows(fields):
            cols = {f: list(payload.get(f) or []) for f in fields}
            count = max(len(v) for v in cols.values())
            return [{f: str(cols[f][i]) if i < len(cols[f]) else "" for f in fields} for i in range(count)]

        context["ea_standard_rows"] = rows(EA_STANDARD_FIELDS)
        context["ea_instrument_rows"] = rows(EA_INSTRUMENT_FIELDS)
        context["ea_reminder_days"] = payload.get("signoff_reminder_days", "")
        return context


class LabStaffHandler(SetupSectionHandler):
    kind = "lab_staff"

    def context(self, service):
        store = LabStaffStore(service.setup_store)
        return {
            "storage_section": store.section_key,
            "staff_rows": [{"name": m.name, "role": "signer" if m.may_sign_off else "staff"} for m in store.load()],
        }

    def read_form(self, form):
        return {"names": form.getlist("staff_name"), "roles": form.getlist("staff_role")}

    def save(self, service, payload):
        LabStaffStore(service.setup_store).update(payload)

    def keep_typed(self, context, payload):
        names = list(payload.get("names") or [])
        roles = list(payload.get("roles") or [])
        context["staff_rows"] = [
            {"name": str(n), "role": str(roles[i]) if i < len(roles) else "staff"} for i, n in enumerate(names)
        ]
        return context


SETUP_HANDLERS: dict[str, SetupSectionHandler] = {
    SETUP_SECTION_STANDARD_THRESHOLDS: StandardThresholdsHandler(),
    SETUP_SECTION_GRAPHITIZATION_SYSTEMS: GraphitizationSystemsHandler(),
    SETUP_SECTION_LAB_WARNING_THRESHOLDS: LabWarningThresholdsHandler(),
    SETUP_SECTION_IMPORT_HEADINGS: ImportHeadingsHandler(),
    SETUP_SECTION_EMAIL: EmailSettingsHandler(),
    SETUP_SECTION_SAMPLE_PHOTOS: SamplePhotosHandler(),
    SETUP_SECTION_EA_CHECKS: EaChecksHandler(),
    SETUP_SECTION_LAB_STAFF: LabStaffHandler(),
}

#: Sections registered in `setup_sections.py` without a handler render the
#: read-only "Section Prepared" placeholder.
PLACEHOLDER_HANDLER = SetupSectionHandler()


def handler_for(section_key: str) -> SetupSectionHandler:
    return SETUP_HANDLERS.get(section_key, PLACEHOLDER_HANDLER)

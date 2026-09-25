"""Synonym vocabulary for recognising submission-sheet labels.

This module is the single place to teach the importer a new spelling.
Everything else keys off canonical field names.

Matching is deliberately forgiving because the sheets come back from
customers with trailing asterisks, embedded newlines, bilingual labels
(`"Vorname *\\nfirst name  * "`), stray punctuation, and inconsistent
casing. `normalize_label` strips all of that down to a comparison key;
`resolve_label` then tries exact match, then containment, then fuzzy
similarity.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable

# --- Canonical field names -------------------------------------------------
#
# Metadata fields (vertical "label | value" rows above the sample table).
# `submitter__*` and `invoice__*` share the same label vocabulary; which
# block a row belongs to is decided by the parser from the section
# heading it sits under, not from the label itself.

SUBMITTER_FIELDS: tuple[str, ...] = (
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

# Labels → canonical contact-field name. Keys are raw label text as seen
# in the wild; they run through `normalize_label` before comparison, so
# case/punctuation/newlines here are irrelevant — only the words matter.
CONTACT_LABEL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "salutation": ("anrede", "salutation"),
    "title": ("titel", "title", "akad titel", "academic title"),
    "first_name": ("vorname", "first name", "firstname", "given name", "forename"),
    "last_name": ("nachname", "last name", "lastname", "surname", "family name", "name"),
    "organisation": ("organisation", "organization", "firma", "company", "org"),
    "institute": ("institut", "institute", "institution", "department", "abteilung"),
    "address_1": ("adresse1", "address1", "adresse 1", "address 1", "strasse", "street", "adresse", "address"),
    "address_2": ("adresse2", "address2", "adresse 2", "address 2", "address line 2"),
    "town": ("stadt", "city", "town", "ort"),
    "postcode": ("plz", "zip", "postcode", "postal code", "zip code", "postleitzahl"),
    "country": ("land", "country", "staat", "nation"),
    "phone_1": ("telefon 1", "phone1", "phone 1", "telefon1", "telephone 1", "tel 1", "telefon", "phone", "tel"),
    "phone_2": ("telefon 2", "phone2", "phone 2", "telefon2", "telephone 2", "tel 2"),
    "fax": ("fax", "telefax"),
    "email": ("email", "e mail", "e-mail", "mail", "emailadresse", "email address"),
    "www": ("www", "website", "web", "homepage", "url", "internet"),
}

# Project-level metadata labels.
PROJECT_LABEL_SYNONYMS: dict[str, tuple[str, ...]] = {
    "project": (
        "projektname",
        "project name",
        "projekt",
        "project",
        "projektbezeichnung",
        "project title",
        "auftragsname",
    ),
    "project_comment": ("projektkommentar", "project comment", "bemerkung projekt", "project note"),
    "desired_date": (
        "wunschtermin",
        "desired date",
        "gewuenschtes datum",
        "due date",
        "deadline",
        "termin",
    ),
    "order_nr": ("bestellnummer", "order number", "order nr", "purchase order", "bestellnr"),
}

# Section headings that switch the parser between the "submitter" block
# and the "invoice recipient" block. Matched by containment, since these
# headings are long bilingual sentences.
SUBMITTER_SECTION_MARKERS: tuple[str, ...] = (
    "angaben zum auftraggeber",
    "customer data",
    "einsender",
    "submitter",
    "kundendaten",
)

INVOICE_SECTION_MARKERS: tuple[str, ...] = (
    "rechnungsadresse",
    "rechnungs adresse",
    "invoice address",
    "accounting address",
    "billing address",
)

# The "is this address also the accounting address?" yes/no row. When it
# says yes (or the invoice block is empty) we bill the submitter.
SAME_INVOICE_ADDRESS_MARKERS: tuple[str, ...] = (
    "rechnungsadresse ja nein",
    "accounting address yes no",
    "rechnung an diese adresse",
    "this address also for accounting",
)

# Heading that introduces the sample table ("Probenliste / sample list").
SAMPLE_TABLE_SECTION_MARKERS: tuple[str, ...] = (
    "probenliste",
    "sample list",
    "probenlist",
    "samples",
)

# --- Sample table columns --------------------------------------------------
#
# Canonical sample column → synonyms. The parser finds the header row by
# scoring each row against this table, so the sample table can sit at any
# row and its columns can appear in any order.

SAMPLE_COLUMN_SYNONYMS: dict[str, tuple[str, ...]] = {
    "user_label": (
        "probenname",
        "sample name",
        "probenbezeichnung",
        "sample label",
        "probe",
        "sample id",
        "sample",
        "name",
    ),
    "user_label_nr": (
        "sample nr",
        "sample no",
        "sample number",
        "probennummer",
        "proben nr",
        "sample nr.",
        "lab nr",
        "sample label nr",
    ),
    "user_desc1": (
        "sample descript 1",
        "sample description 1",
        "beschreibung 1",
        "description 1",
        "descript 1",
        "probenbeschreibung 1",
        "description",
    ),
    "user_desc2": (
        "sample descript 2",
        "sample description 2",
        "beschreibung 2",
        "description 2",
        "descript 2",
        "probenbeschreibung 2",
    ),
    "weight": ("weight mg", "gewicht mg", "weight", "gewicht", "masse", "mass mg", "mass"),
    "material": ("material", "materialien", "probenmaterial", "sample material"),
    "type": ("type", "typ", "sample type", "probentyp", "probenart"),
    "fraction": ("fraction", "fraktion", "sample fraction"),
    "user_comment": ("comment", "kommentar", "bemerkung", "note", "notes", "remarks", "anmerkung"),
    "pre_sub_treat": (
        "pretreatment",
        "pre treatment",
        "vorbehandlung",
        "pre sub treat",
        "pre-treatment",
    ),
    "sampling_date": ("sampling date", "probenahmedatum", "probennahme datum", "date sampled"),
}

# Columns the importer will write to `sample_t`. Anything the user maps
# outside this set is rejected by the commit step.
IMPORTABLE_SAMPLE_FIELDS: frozenset[str] = frozenset(SAMPLE_COLUMN_SYNONYMS)

# Human labels for the review UI.
SAMPLE_FIELD_LABELS: dict[str, str] = {
    "user_label": "Sample Label",
    "user_label_nr": "Sample Label #",
    "user_desc1": "Description 1",
    "user_desc2": "Description 2",
    "weight": "Weight (mg)",
    "material": "Material",
    "type": "Type",
    "fraction": "Fraction",
    "user_comment": "Comment",
    "pre_sub_treat": "Pre-sub Treatment",
    "sampling_date": "Sampling Date",
}

CONTACT_FIELD_LABELS: dict[str, str] = {
    "salutation": "Salutation",
    "title": "Title",
    "first_name": "First Name",
    "last_name": "Last Name",
    "organisation": "Organisation",
    "institute": "Institute",
    "address_1": "Address 1",
    "address_2": "Address 2",
    "town": "Town",
    "postcode": "Postcode",
    "country": "Country",
    "phone_1": "Phone 1",
    "phone_2": "Phone 2",
    "fax": "Fax",
    "email": "Email",
    "www": "Website",
    "language": "Language",
    "user_comment": "Comment",
}

#: Contact fields the operator can edit when creating a NEW submitter.
#: Wider than what the sheet carries — salutation/title/language/comment
#: are lab-side attributes the sheet never provides but the record needs
#: (language drives which e-mail template is used).
EDITABLE_CONTACT_FIELDS: tuple[str, ...] = (
    "salutation",
    "title",
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
    "language",
    "user_comment",
)

#: Fields rendered as a free-text textarea rather than a single-line input.
MULTILINE_CONTACT_FIELDS: frozenset[str] = frozenset({"user_comment"})

#: `user_t.language` is a 2-char code; offer the ones the lab uses.
LANGUAGE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("de", "German"),
    ("en", "English"),
)

# Values that mean "the customer left this blank on purpose".
BLANK_EQUIVALENT_TOKENS: frozenset[str] = frozenset(
    {"", "n a", "na", "n/a", "none", "keine", "kein", "entfaellt", "-", "--", "undefined", "null"}
)

# Boolean-ish answers used by the yes/no rows.
TRUTHY_TOKENS: frozenset[str] = frozenset({"ja", "yes", "y", "j", "true", "1", "x", "wahr"})
FALSY_TOKENS: frozenset[str] = frozenset({"nein", "no", "n", "false", "0", "falsch"})

# Boilerplate that appears in the template's helper columns; never a value.
NOISE_MARKERS: tuple[str, ...] = (
    "erforderlich",
    "required",
    "eintragen, falls nicht anwendbar",
    "enter 'n.a",
    "nur falls unterschiedlich",
    "only if different",
    "angaben mit",
    "entries marked as",
    "or z.b. verwaltung",
    "or e.g. accounting",
)


# --- Normalisation + matching ---------------------------------------------


def normalize_label(value: object) -> str:
    """Reduce a raw cell label to a comparison key.

    Lowercases, strips accents, replaces every run of non-alphanumeric
    characters (including the newlines that join the German and English
    halves of a bilingual label) with a single space.

    >>> normalize_label("Vorname *\\nfirst name  * ")
    'vorname first name'
    >>> normalize_label("weight mg")
    'weight mg'
    """
    if value is None:
        return ""
    text = str(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("ß", "ss")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def is_noise(value: object) -> bool:
    """True for the template's instructional helper text, which sits in
    neighbouring columns and must never be mistaken for a value."""
    key = normalize_label(value)
    if not key:
        return False
    return any(normalize_label(marker) in key for marker in NOISE_MARKERS)


def is_blank_equivalent(value: object) -> bool:
    """True for empty cells and the tokens customers use to mean 'empty'."""
    if value is None:
        return True
    if isinstance(value, str):
        return normalize_label(value) in BLANK_EQUIVALENT_TOKENS
    return False


def parse_boolean(value: object) -> bool | None:
    """Parse a yes/no cell. Returns None when the answer is unreadable."""
    key = normalize_label(value)
    if not key:
        return None
    first = key.split(" ", 1)[0]
    if key in TRUTHY_TOKENS or first in TRUTHY_TOKENS:
        return True
    if key in FALSY_TOKENS or first in FALSY_TOKENS:
        return False
    return None


def contains_marker(value: object, markers: Iterable[str]) -> bool:
    """True when the normalised `value` contains any of `markers`."""
    key = normalize_label(value)
    if not key:
        return False
    return any(normalize_label(marker) in key for marker in markers)


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def resolve_label(
    raw: object,
    synonyms: dict[str, tuple[str, ...]],
    *,
    min_ratio: float = 0.86,
) -> tuple[str | None, float]:
    """Map a raw label cell to a canonical field name.

    Returns `(field_name, confidence)`, or `(None, 0.0)` when nothing
    matches well enough. Three passes, most-confident first:

    1. Exact match on the normalised key.
    2. Whole-word containment — handles bilingual labels where the
       German and English names are concatenated
       (`"vorname first name"` contains `"first name"`).
    3. Fuzzy ratio, to absorb typos and minor rewording.

    Longer synonyms are tried before shorter ones so that
    `"sample descript 1"` wins over the bare `"description"`, and
    `"telefon 2"` never loses to `"telefon"`.
    """
    key = normalize_label(raw)
    if not key:
        return None, 0.0

    ranked: list[tuple[str, str]] = []
    for field, options in synonyms.items():
        for option in options:
            ranked.append((normalize_label(option), field))
    # Longest synonym first: more specific labels take precedence.
    ranked.sort(key=lambda pair: len(pair[0]), reverse=True)

    for option_key, field in ranked:
        if option_key and option_key == key:
            return field, 1.0

    for option_key, field in ranked:
        if option_key and re.search(rf"(?:^|\s){re.escape(option_key)}(?:\s|$)", key):
            return field, 0.95

    best_field: str | None = None
    best_ratio = 0.0
    for option_key, field in ranked:
        if not option_key:
            continue
        ratio = _similarity(key, option_key)
        if ratio > best_ratio:
            best_ratio, best_field = ratio, field
    if best_field is not None and best_ratio >= min_ratio:
        return best_field, round(best_ratio, 3)
    return None, 0.0


def merge_synonyms(
    base: dict[str, tuple[str, ...]],
    extra: dict[str, list[str]] | None,
) -> dict[str, tuple[str, ...]]:
    """Overlay operator-taught headings on top of the built-in vocabulary.

    Setup → "Import Column Headings" persists extra spellings per field
    (a customer who writes "Probenkennung" for the sample name). Those
    are *added* to the built-ins rather than replacing them, so teaching
    the importer a new wording can never break recognition of the
    standard template.

    Unknown field names in `extra` are ignored — the Setup editor only
    offers real fields, but the JSON file is hand-editable.
    """
    if not extra:
        return base
    merged: dict[str, tuple[str, ...]] = {}
    for field, options in base.items():
        added = [
            str(item).strip()
            for item in extra.get(field, [])
            if str(item).strip()
        ]
        if not added:
            merged[field] = options
            continue
        # De-duplicate on the normalised key, keeping built-ins first.
        seen = {normalize_label(o) for o in options}
        combined = list(options)
        for item in added:
            key = normalize_label(item)
            if key and key not in seen:
                seen.add(key)
                combined.append(item)
        merged[field] = tuple(combined)
    return merged


def suggest_from_choices(
    raw: object,
    choices: Iterable[str],
    *,
    limit: int = 5,
    min_ratio: float = 0.45,
) -> list[tuple[str, float]]:
    """Rank `choices` by similarity to `raw`.

    Used for the lookup columns (material / type / fraction): when the
    customer writes something that isn't in `material_t`, the review UI
    offers the closest existing entries instead of failing the row.
    """
    key = normalize_label(raw)
    if not key:
        return []
    scored: list[tuple[str, float]] = []
    for choice in choices:
        choice_key = normalize_label(choice)
        if not choice_key:
            continue
        ratio = _similarity(key, choice_key)
        # Substring hits are strong signals that a plain ratio underrates
        # (e.g. "shell" inside "shell terrestrial").
        if choice_key in key or key in choice_key:
            ratio = max(ratio, 0.9)
        if ratio >= min_ratio:
            scored.append((choice, round(ratio, 3)))
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return scored[:limit]


def match_choice(raw: object, choices: Iterable[str]) -> str | None:
    """Return the lookup entry that matches `raw` exactly (after
    normalisation), else None. Exactness matters here — silently
    coercing 'collagen' to 'collagen user prep.' would corrupt data, so
    anything short of an exact hit goes to the review UI as a suggestion."""
    key = normalize_label(raw)
    if not key:
        return None
    for choice in choices:
        if normalize_label(choice) == key:
            return choice
    return None


__all__ = [
    "BLANK_EQUIVALENT_TOKENS",
    "CONTACT_FIELD_LABELS",
    "CONTACT_LABEL_SYNONYMS",
    "EDITABLE_CONTACT_FIELDS",
    "IMPORTABLE_SAMPLE_FIELDS",
    "INVOICE_SECTION_MARKERS",
    "LANGUAGE_OPTIONS",
    "MULTILINE_CONTACT_FIELDS",
    "PROJECT_LABEL_SYNONYMS",
    "SAMPLE_COLUMN_SYNONYMS",
    "SAMPLE_FIELD_LABELS",
    "SAMPLE_TABLE_SECTION_MARKERS",
    "SAME_INVOICE_ADDRESS_MARKERS",
    "SUBMITTER_FIELDS",
    "SUBMITTER_SECTION_MARKERS",
    "contains_marker",
    "is_blank_equivalent",
    "is_noise",
    "match_choice",
    "merge_synonyms",
    "normalize_label",
    "parse_boolean",
    "resolve_label",
    "suggest_from_choices",
]

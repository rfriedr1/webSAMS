"""One label per field, on every page (sams_web/field_labels.py).

Guards against the drift that had the project's sample table say
"User Label" while the sample page said "Sample Label" for the same
column: every label comes from FIELD_LABELS, and a template may not spell
a field's label out by hand.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy.inspection import inspect

from sams_web import models
from sams_web.field_labels import FIELD_LABELS, default_label, field_label
from sams_web.routers.pages_shared import format_table_header_label
from sams_web.viewmodels import detail_sections_sample_lab, detail_sections_user_project
from sams_web.viewmodels.detail_sections_user_project import (
    PROJECT_SAMPLE_COLUMNS,
    SUBMITTER_PROJECT_COLUMNS,
)

TEMPLATES = Path(__file__).resolve().parent.parent / "sams_web" / "templates"


@pytest.mark.parametrize(
    "model", [models.Submitter, models.Project, models.Sample, models.Preparation, models.Target]
)
def test_every_model_column_has_a_label(model):
    missing = [a.key for a in inspect(model).column_attrs if a.key not in FIELD_LABELS]
    assert not missing, f"add {model.__name__} columns to FIELD_LABELS: {missing}"


def test_table_heads_and_detail_rows_share_one_label():
    assert format_table_header_label("user_label") == field_label("user_label") == "Sample Label"
    assert format_table_header_label("USER_LABEL") == "Sample Label"


def test_viewmodels_keep_no_label_dict_of_their_own():
    for module in (detail_sections_sample_lab, detail_sections_user_project):
        own = [name for name in vars(module) if name.endswith("_FIELD_LABELS")]
        assert not own, f"{module.__name__} defines {own}; use sams_web.field_labels"


def test_related_table_columns_are_registered():
    for key in (*PROJECT_SAMPLE_COLUMNS, *SUBMITTER_PROJECT_COLUMNS):
        assert key in FIELD_LABELS


def test_labels_are_title_case():
    # Every word starts with a capital, except short joining words after
    # the first ("Free of Charge") and symbols ("δ¹³C", "1σ", "(%)").
    small = {"of", "to", "in", "and", "for", "a", "the", "on"}
    wrong = {}
    for key, label in FIELD_LABELS.items():
        for index, word in enumerate(label.split()):
            if index and word in small:
                continue
            if word[:1].islower() and not word.startswith("δ"):
                wrong[key] = label
    assert not wrong, f"labels not in Title Case: {wrong}"


# ---- Templates may not spell out a field label ---------------------------

_TAG = re.compile(r"<(th|label)\b([^>]*)>(.*?)</\1>", re.S)


def _norm(text: str) -> str:
    text = text.lower().replace("δ¹³c", "d13c")
    return re.sub(r"[^a-z0-9#%µ]", "", text)


def _field_spellings() -> dict[str, str]:
    """Every way a field's name tends to be written → its key."""
    spellings: dict[str, str] = {}
    for key, label in FIELD_LABELS.items():
        for variant in (label, default_label(key), key.replace("_", " ").title(), key):
            normalized = _norm(variant)
            if normalized:
                spellings.setdefault(normalized, key)
    return spellings


def _literal_text(inner: str) -> str:
    # Only the literal part: stop at the first Jinja expression or tag.
    cut = re.split(r"\{\{|\{%|<", inner, maxsplit=1)[0]
    return cut.strip()


def test_templates_take_field_labels_from_the_registry():
    spellings = _field_spellings()
    offenders = []
    for path in sorted(TEMPLATES.rglob("*.html")):
        for match in _TAG.finditer(path.read_text(encoding="utf-8")):
            # `data-own-label`: a field that is not a registry column (the EA
            # check's standard weight is ea_check_t.weight_mg, not a sample's).
            if "data-own-label" in match.group(2):
                continue
            text = _literal_text(match.group(3))
            key = spellings.get(_norm(text)) if text else None
            if key:
                offenders.append(f"{path.name}: <{match.group(1)}>{text}  → {{{{ field_label('{key}') }}}}")
    assert not offenders, "hand-written field labels:\n" + "\n".join(offenders)

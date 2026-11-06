"""Import values are converted and clamped by the real `sample_t` column.

The server runs MySQL in strict mode: a value wider than its column, or text
in a numeric column, fails the INSERT and with it the whole import. Kinds and
widths come from `models.Sample`, so the model must mirror the live table.
"""

from __future__ import annotations

import pytest

from sams_web.sample_import.commit import (
    ImportCommitError,
    _build_sample_payload,
    _coerce_number,
    _validate_payload,
)
from sams_web.sample_import.fields import SAMPLE_TARGET_COLUMNS, build_registry
from sams_web.services import TextSanitizer

#: Writable `sample_t` columns as `information_schema.COLUMNS` reports them
#: (db_dmams, checked 2026-11-06). If the table changes, update the model and
#: this snapshot together.
LIVE_SAMPLE_COLUMNS: dict[str, tuple[str, int | None]] = {
    "photo": ("text", 120),
    "type": ("text", 20),
    "material": ("text", 20),
    "fraction": ("text", 20),
    "pre_sub_treat": ("text", 40),
    "weight": ("number", None),
    "preparation": ("text", 100),
    "sampling_date": ("date", None),
    "user_label": ("text", 100),
    "user_label_nr": ("text", 40),
    "user_desc1": ("text", 100),
    "user_desc2": ("text", 40),
    "residue": ("number", None),
    "user_comment": ("text", 100),
    "old_info": ("text", 70),
    "ma_nr": ("integer", None),
    "s_no_leftover": ("integer", None),
    "s_storage_loc": ("text", 45),
    "prep_storage_loc": ("text", 45),
    "lab_comment": ("text", 120),
    "left_over": ("integer", None),
    "storage": ("text", 100),
}


def test_import_targets_match_live_schema():
    actual = {name: (col.kind, col.max_length) for name, col in SAMPLE_TARGET_COLUMNS.items()}
    assert actual == LIVE_SAMPLE_COLUMNS


def _registry_with(*targets: str):
    return build_registry(
        custom_fields=[{"target": t, "label": t, "headings": [f"col {t}"]} for t in targets]
    )


def _payload(values, registry):
    return _build_sample_payload(
        values, project_nr=1, registry=registry, lookup_allowed={}, sanitizer=TextSanitizer
    )


def _plan(values, registry):
    return _validate_payload(
        {"project": {"project": "P"}, "samples": [{"row_number": 7, "values": values}]},
        registry,
    )


def test_long_customer_comment_is_clamped_to_column_width():
    # user_comment is VARCHAR(100); a longer comment used to fail the import.
    payload = _payload({"user_label": "A", "user_comment": "x" * 250}, build_registry())
    assert len(payload["user_comment"]) == 100


def test_custom_text_field_uses_live_width():
    payload = _payload({"user_label": "A", "old_info": "y" * 90}, _registry_with("old_info"))
    assert len(payload["old_info"]) == 70


@pytest.mark.parametrize(
    ("target", "raw", "expected"),
    [
        ("ma_nr", "12", 12),
        ("ma_nr", "12,0", 12),
        ("ma_nr", 7.0, 7),
        ("left_over", " 3 ", 3),
        ("residue", "12,5", 12.5),
        ("residue", 4, 4.0),
    ],
)
def test_custom_numeric_field_is_converted(target, raw, expected):
    registry = _registry_with(target)
    payload = _payload({"user_label": "A", target: raw}, registry)
    assert payload[target] == expected
    assert type(payload[target]) is type(expected)


@pytest.mark.parametrize(
    ("target", "raw"),
    [("ma_nr", "abc"), ("ma_nr", "1.5"), ("residue", "ca. 5 mg"), ("left_over", "some")],
)
def test_unreadable_number_is_rejected_before_any_write(target, raw):
    with pytest.raises(ImportCommitError, match=r"Row 7, field"):
        _plan({"user_label": "A", target: raw}, _registry_with(target))


def test_empty_number_keeps_the_default():
    registry = _registry_with("s_no_leftover")
    assert _payload({"user_label": "A", "s_no_leftover": ""}, registry)["s_no_leftover"] == 0
    assert "weight" not in _payload({"user_label": "A", "weight": ""}, build_registry())
    assert _plan({"user_label": "A", "weight": ""}, build_registry()).rows


def test_weight_from_the_review_table_is_kept():
    assert _payload({"user_label": "A", "weight": 4.2}, build_registry())["weight"] == 4.2


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        (None, "number", (None, None)),
        ("", "integer", (None, None)),
        (True, "integer", (1, None)),
        ("2", "number", (2.0, None)),
    ],
)
def test_coerce_number(raw, kind, expected):
    assert _coerce_number(raw, kind) == expected

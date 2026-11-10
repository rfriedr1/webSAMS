"""Duplicate sample names in a submission sheet.

The wizard re-checks live on the Lab values step (`labelKey()` /
`duplicateLabels()` in `sample-import.js`); these pin the comparison rule
both sides share.
"""

from sams_web.sample_import.draft import SampleDraft
from sams_web.sample_import.parser import _flag_duplicate_labels, sample_label_key


def _samples(*labels):
    return [
        SampleDraft(row_number=10 + i, values={"user_label": label} if label is not None else {})
        for i, label in enumerate(labels)
    ]


def test_label_key_ignores_case_and_spacing_but_keeps_accents():
    assert sample_label_key("Bone 1") == sample_label_key("  bone   1 ")
    assert sample_label_key("Häck") != sample_label_key("Hack")
    assert sample_label_key(None) == ""


def test_unique_names_get_no_warning():
    samples = _samples("A-1", "A-2", "A-3")
    _flag_duplicate_labels(samples)
    assert all(not s.issues for s in samples)


def test_repeat_is_flagged_on_the_later_rows_and_names_the_first():
    samples = _samples("Bone 1", "Bone 2", "bone  1", "BONE 1")
    _flag_duplicate_labels(samples)
    assert not samples[0].issues and not samples[1].issues
    for later in (samples[2], samples[3]):
        (issue,) = later.issues
        assert issue.severity == "warning"
        assert issue.target == "user_label"
        assert "row 10" in issue.message


def test_rows_without_a_name_are_not_duplicates_of_each_other():
    samples = _samples("", None, "  ")
    _flag_duplicate_labels(samples)
    assert all(not s.issues for s in samples)


def _payload(*rows):
    return {
        "project": {"project": "P"},
        "samples": [
            {"row_number": number, "include": include, "values": {"user_label": label}}
            for number, label, include in rows
        ],
    }


def test_commit_refuses_a_repeated_name_among_imported_rows():
    import pytest

    from sams_web.sample_import.commit import ImportCommitError, _validate_payload
    from sams_web.sample_import.fields import build_registry

    payload = _payload((20, "Bone 1", True), (21, "Bone 2", True), (22, " bone  1", True))
    with pytest.raises(ImportCommitError, match=r"Row 22 has the same sample name as row 20"):
        _validate_payload(payload, build_registry())


def test_commit_ignores_a_repeat_in_a_row_left_out():
    from sams_web.sample_import.commit import _validate_payload
    from sams_web.sample_import.fields import build_registry

    payload = _payload((20, "Bone 1", True), (21, "Bone 1", False))
    assert [n for n, _ in _validate_payload(payload, build_registry()).rows] == [20]

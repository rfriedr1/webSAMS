from sams_web.sample_import.commit import _build_sample_payload


def test_sample_flags_written_as_zero_not_null():
    payload = _build_sample_payload(
        {},
        project_nr=1,
        importable=set(),
        field_targets={},
        field_widths={},
        lookup_allowed={},
        sanitizer=None,
    )
    for col in ("not_tobedated", "s_no_leftover", "c_n_isotop_a", "c_n_isotop_a_moved"):
        assert payload[col] == 0


def _payload(values):
    return _build_sample_payload(
        values,
        project_nr=1,
        importable={"cn_isotop_a", "dendro_a"},
        field_targets={},
        field_widths={},
        lookup_allowed={},
        sanitizer=None,
    )


def test_extra_analyses_default_off():
    payload = _payload({})
    assert payload["c_n_isotop_a"] == 0
    assert payload["dendro_a"] == 0


def test_extra_analyses_coerced_to_flags():
    assert _payload({"cn_isotop_a": 1, "dendro_a": True})["dendro_a"] == 1
    assert _payload({"cn_isotop_a": "1"})["c_n_isotop_a"] == 1
    assert _payload({"dendro_a": "0"})["dendro_a"] == 0
    assert _payload({"dendro_a": None})["dendro_a"] == 0
    assert _payload({"dendro_a": "false"})["dendro_a"] == 0


def test_extra_analyses_not_importable_from_sheet():
    from sams_web.sample_import.fields import BLOCKED_TARGET_COLUMNS

    assert {"c_n_isotop_a", "dendro_a"} <= BLOCKED_TARGET_COLUMNS

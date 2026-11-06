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

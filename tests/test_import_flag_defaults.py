from sams_web.sample_import.commit import _build_sample_payload
from sams_web.sample_import.fields import build_registry

REGISTRY = build_registry()


def _payload(values, registry=REGISTRY):
    return _build_sample_payload(
        values,
        project_nr=1,
        registry=registry,
        lookup_allowed={},
        sanitizer=None,
    )


def test_sample_flags_written_as_zero_not_null():
    payload = _payload({})
    for col in ("not_tobedated", "s_no_leftover", "c_n_isotop_a", "c_n_isotop_a_moved"):
        assert payload[col] == 0


def test_extra_analyses_default_off():
    payload = _payload({})
    assert payload["c_n_isotop_a"] == 0
    assert payload["dendro_a"] == 0


def test_extra_analyses_coerced_to_flags():
    assert _payload({"cn_isotop_a": 1, "dendro_a": True})["dendro_a"] == 1
    assert _payload({"cn_isotop_a": "1"})["c_n_isotop_a"] == 1
    assert _payload({"dendro_a": "0"})["dendro_a"] == 0
    assert _payload({"dendro_a": None})["dendro_a"] == 0

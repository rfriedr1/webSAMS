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


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass


def _repo():
    from sams_web.repositories import SamsRepository

    repo = SamsRepository.__new__(SamsRepository)
    repo.session = _FakeSession()
    return repo


def test_new_preparation_flags_written_as_zero_not_null():
    # The lab queues filter on `stop = 0`; NULL would hide the record.
    prep = _repo().create_blank_prep(sample_nr=1, prep_nr=1)
    assert prep.stop == 0
    assert prep.p_no_leftover == 0


def test_new_target_discarded_flag_written_as_zero_not_null():
    target = _repo().create_blank_target(sample_nr=1, prep_nr=1, target_nr=1)
    assert target.stop == 0

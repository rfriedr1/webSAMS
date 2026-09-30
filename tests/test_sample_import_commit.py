from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from sams_web.sample_import.commit import _create_samples, needs_no_preparation
from sams_web.services import TextSanitizer


@pytest.mark.parametrize(
    ("steps", "expected"),
    [
        (["none", None, None, None, None], True),
        (["None ", "", "none", None, None], True),
        # A real method after "none" is still preparation.
        (["none", "ABA", None, None, None], False),
        (["ABA", None, None, None, None], False),
        # Nothing chosen at all is "not decided yet", not "no preparation".
        ([None, None, None, None, None], False),
        ([], False),
    ],
)
def test_needs_no_preparation(steps, expected):
    assert needs_no_preparation(steps) is expected


class _FakeSession:
    def flush(self) -> None:
        pass


class _FakeRepo:
    def __init__(self) -> None:
        self.preps: list[SimpleNamespace] = []

    def get_materials(self):
        return ["undefined", "bone"]

    def get_sample_types(self):
        return ["undefined", "arch"]

    def get_fractions(self):
        return ["undefined"]

    def get_methods(self):
        return ["none", "ABA"]

    def create_sample(self, payload):
        return SimpleNamespace(sample_nr=50000 + len(self.preps))

    def create_blank_prep(self, sample_nr, prep_nr=1):
        prep = SimpleNamespace(sample_nr=sample_nr, prep_nr=prep_nr, prep_end=None, prep_start=None)
        self.preps.append(prep)
        return prep

    def create_blank_target(self, sample_nr, prep_nr=1, target_nr=1):
        return SimpleNamespace()


def test_import_closes_preparation_only_for_no_prep_rows():
    repo = _FakeRepo()
    rows = [
        (1, {"user_label": "A", "step1_method": "none"}),
        (2, {"user_label": "B", "step1_method": "ABA"}),
        (3, {"user_label": "C", "step1_method": "none", "step2_method": "ABA"}),
        (4, {"user_label": "D"}),
    ]
    _create_samples(
        repo,
        _FakeSession(),
        rows,
        project_nr=1,
        today=date(2026, 9, 30),
        registry=None,
        sanitizer=TextSanitizer,
    )
    assert [p.prep_end for p in repo.preps] == [datetime(2026, 9, 30), None, None, None]
    assert all(p.prep_start is None for p in repo.preps)
    assert repo.preps[0].step1_method == "none"

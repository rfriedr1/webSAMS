"""Record actions (sams_web/record_actions.py, ADR-0007)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sams_web import record_actions as ra
from sams_web.field_labels import FIELD_LABELS
from sams_web.models import Base, Preparation, Project, Sample, Submitter
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore


@pytest.fixture()
def service(tmp_path: Path) -> SamsService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, class_=Session)()
    setup_store = SetupStore(tmp_path / "setup.json")
    svc = SamsService(session, threshold_store=ThresholdStore(setup_store), setup_store=setup_store)

    session.add(Submitter(user_nr=1, last_name="Miller"))
    session.add(Submitter(user_nr=2, last_name="Other"))
    for project_nr, user_nr in ((10, 1), (11, 1), (20, 2)):
        session.add(Project(
            project_nr=project_nr, user_nr=user_nr, project=f"P{project_nr}",
            in_date=date(2026, 1, 1), desired_date=date(2026, 4, 1),
        ))
    # Project 10: samples 100-102; project 11: 110; project 20: 200.
    for sample_nr, project_nr in ((100, 10), (101, 10), (102, 10), (110, 11), (200, 20)):
        session.add(Sample(
            sample_nr=sample_nr, project_nr=project_nr, user_label=f"S{sample_nr}",
            type="arch", material="bone", fraction="collagen",
        ))
        session.add(Preparation(sample_nr=sample_nr, prep_nr=1))
    session.add(Preparation(sample_nr=100, prep_nr=2))
    session.commit()
    return svc


def _sample(service: SamsService, nr: int) -> Sample:
    return service.session.get(Sample, nr)


# ---- Registry --------------------------------------------------------------


def test_every_action_has_its_twin_a_label_and_a_writable_field():
    for action in ra.RECORD_ACTIONS.values():
        twin_key = action.key.rsplit(".", 1)[0] + (".clear" if action.verb == "Set" else ".set")
        assert twin_key in ra.RECORD_ACTIONS, action.key
        assert action.field in FIELD_LABELS, action.field
        config = ra.KINDS[action.child].config
        assert action.field not in config.read_only_fields
        assert hasattr(config.model, action.field)
        for owner in action.owners:
            assert ra.OWNER_ROW_KIND[owner]


def test_project_page_has_no_project_level_actions():
    with pytest.raises(KeyError):
        ra.action_for("project", "project.return_to_sender.set")
    kinds = [group["kind"] for group in ra.action_menu("project")]
    assert kinds == ["sample", "preparation"]
    assert [g["kind"] for g in ra.action_menu("submitter")] == ["sample", "preparation", "project"]


def test_parse_selection():
    assert ra.parse_selection("") == []
    assert ra.parse_selection(" 12, 13,12 ;14") == [12, 13, 14]
    with pytest.raises(ValueError):
        ra.parse_selection("12,abc")


# ---- Plan / apply ----------------------------------------------------------


def test_set_on_all_samples_of_a_project(service):
    action = ra.action_for("project", "sample.c_n_isotop_a.set")
    preview = ra.plan(service, action, "project", 10, [])
    assert [c.record.ref for c in preview.changes] == ["100", "101", "102"]
    assert _sample(service, 100).c_n_isotop_a is None  # preview wrote nothing

    outcome = ra.apply(service, action, "project", 10, [])
    assert outcome.changed == 3
    assert [_sample(service, nr).c_n_isotop_a for nr in (100, 101, 102)] == [1, 1, 1]
    assert _sample(service, 110).c_n_isotop_a is None  # other project untouched
    assert "set on 3 samples" in outcome.notice()


def test_ticked_rows_only_and_already_set_counted(service):
    _sample(service, 101).dendro_a = 1
    service.session.commit()
    action = ra.action_for("project", "sample.dendro_a.set")
    outcome = ra.apply(service, action, "project", 10, [100, 101])
    assert outcome.changed == 1
    assert outcome.unchanged == 1
    assert _sample(service, 102).dendro_a is None


def test_clear_treats_empty_as_already_clear(service):
    action = ra.action_for("project", "sample.dendro_a.clear")
    preview = ra.plan(service, action, "project", 10, [])
    assert preview.changes == ()
    assert preview.unchanged == 3


def test_a_sample_of_another_project_is_refused(service):
    action = ra.action_for("project", "sample.c_n_isotop_a.set")
    with pytest.raises(ValueError, match="Sample 200 is not in project 10"):
        ra.plan(service, action, "project", 10, [100, 200])


def test_preparations_are_reached_through_the_ticked_samples(service):
    action = ra.action_for("project", "preparation.p_no_leftover.set")
    preview = ra.plan(service, action, "project", 10, [100])
    assert [c.record.ref for c in preview.changes] == ["100 / 1", "100 / 2"]
    ra.apply(service, action, "project", 10, [100])
    assert service.session.get(Preparation, (100, 2)).p_no_leftover == 1
    assert service.session.get(Preparation, (101, 1)).p_no_leftover is None


def test_submitter_reaches_samples_of_ticked_projects(service):
    action = ra.action_for("submitter", "sample.c_n_isotop_a.set")
    preview = ra.plan(service, action, "submitter", 1, [11])
    assert [c.record.ref for c in preview.changes] == ["110"]
    preview_all = ra.plan(service, action, "submitter", 1, [])
    assert sorted(c.record.ref for c in preview_all.changes) == ["100", "101", "102", "110"]


def test_submitter_project_flag(service):
    action = ra.action_for("submitter", "project.return_to_sender.set")
    outcome = ra.apply(service, action, "submitter", 1, [])
    assert outcome.changed == 2
    assert service.session.get(Project, 10).return_to_sender == 1
    assert service.session.get(Project, 20).return_to_sender is None


def test_record_its_detail_page_would_refuse_is_listed_and_skipped(service):
    # An old sample with no type: its detail page refuses any save.
    _sample(service, 101).type = None
    service.session.commit()
    action = ra.action_for("project", "sample.c_n_isotop_a.set")
    preview = ra.plan(service, action, "project", 10, [])
    assert [r.record.ref for r in preview.refused] == ["101"]
    assert "required" in preview.refused[0].reason
    assert [c.record.ref for c in preview.changes] == ["100", "102"]

    outcome = ra.apply(service, action, "project", 10, [])
    assert outcome.changed == 2
    assert _sample(service, 101).c_n_isotop_a is None
    assert _sample(service, 100).c_n_isotop_a == 1
    assert "1 not changed" in outcome.notice()


def test_clearing_cn_after_the_move_warns(service):
    sample = _sample(service, 100)
    sample.c_n_isotop_a = 1
    sample.c_n_isotop_a_moved = 1
    service.session.commit()
    action = ra.action_for("project", "sample.c_n_isotop_a.clear")
    preview = ra.plan(service, action, "project", 10, [])
    assert preview.warnings == ("Sample 100 was already moved to C/N analysis.",)
    assert preview.as_json()["change_count"] == 1

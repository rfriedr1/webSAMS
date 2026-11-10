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
    twins = {"Set": "clear", "Edit": "clear", "Clear": None}
    for action in ra.RECORD_ACTIONS.values():
        base = action.key.rsplit(".", 1)[0]
        if action.verb == "Clear":
            assert f"{base}.set" in ra.RECORD_ACTIONS or f"{base}.edit" in ra.RECORD_ACTIONS, action.key
        else:
            assert f"{base}.{twins[action.verb]}" in ra.RECORD_ACTIONS, action.key
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
    assert [g["kind"] for g in ra.action_menu("submitter")] == ["project"]


def test_submitter_page_offers_only_project_flags():
    keys = {act["key"] for g in ra.action_menu("submitter") for item in g["items"] for act in item["actions"]}
    assert keys == {
        "project.return_to_sender.set", "project.return_to_sender.clear",
        "project.prep_return_to_sender.set", "project.prep_return_to_sender.clear",
    }
    for key in ("sample.c_n_isotop_a.set", "sample.dendro_a.set", "sample.s_no_leftover.set", "preparation.p_no_leftover.set"):
        with pytest.raises(KeyError):
            ra.action_for("submitter", key)


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


def test_submitter_project_flag(service):
    action = ra.action_for("submitter", "project.return_to_sender.set")
    outcome = ra.apply(service, action, "submitter", 1, [])
    assert outcome.changed == 2
    assert service.session.get(Project, 10).return_to_sender == 1
    assert service.session.get(Project, 20).return_to_sender is None


def test_submitter_ticked_projects_only(service):
    action = ra.action_for("submitter", "project.prep_return_to_sender.set")
    preview = ra.plan(service, action, "submitter", 1, [11])
    assert [c.record.ref for c in preview.changes] == ["11"]
    with pytest.raises(ValueError, match="Project 20 is not in submitter 1"):
        ra.plan(service, action, "submitter", 1, [20])


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


# ---- Storage locations (Edit / Clear) --------------------------------------


def test_storage_location_actions_are_project_only():
    for key in ("sample.s_storage_loc.edit", "sample.prep_storage_loc.edit", "sample.s_storage_loc.clear"):
        assert ra.action_for("project", key)
        with pytest.raises(KeyError):
            ra.action_for("submitter", key)
    labels = [item["label"] for group in ra.action_menu("project") for item in group["items"]]
    assert "Sample Storage Location" in labels and "Prep Storage Location" in labels


def test_edit_preview_lists_every_record_with_its_value(service):
    _sample(service, 100).s_storage_loc = "Box 1"
    _sample(service, 101).type = None  # its page refuses any save
    service.session.commit()
    action = ra.action_for("project", "sample.s_storage_loc.edit")
    payload = ra.plan(service, action, "project", 10, []).as_json()
    assert payload["mode"] == "edit"
    assert payload["editor"]["max_length"] == 45
    rows = {row["ref"]: row for row in payload["editor"]["rows"]}
    assert rows["100"]["value"] == "Box 1"
    assert rows["102"]["value"] == ""
    assert rows["101"]["refused"] and rows["100"]["refused"] is None
    assert payload["change_count"] == 0
    assert _sample(service, 101).type is None  # probe rolled back


def test_storage_location_editor_offers_the_taken_mark_and_export_columns(service):
    for key in ("sample.s_storage_loc.edit", "sample.prep_storage_loc.edit"):
        editor = ra.plan(service, ra.action_for("project", key), "project", 10, []).as_json()["editor"]
        # "Add E" (entnommen) appends this in the browser: 266 -> 266E.
        assert editor["mark_suffix"] == ra.STORAGE_TAKEN_SUFFIX == "E"
        # The Excel download heads its columns with the registry labels.
        assert editor["columns"] == ["Sample #", "Sample Label"]


def test_a_marked_location_is_saved_like_any_edit(service):
    _sample(service, 100).s_storage_loc = "266"
    service.session.commit()
    action = ra.action_for("project", "sample.s_storage_loc.edit")
    outcome = ra.apply(service, action, "project", 10, [], values={"100": "266E"})
    assert outcome.changed == 1
    assert _sample(service, 100).s_storage_loc == "266E"


def test_edit_writes_only_the_posted_rows(service):
    _sample(service, 100).s_storage_loc = "Box 1"
    _sample(service, 101).s_storage_loc = "Box 1"
    service.session.commit()
    action = ra.action_for("project", "sample.s_storage_loc.edit")
    outcome = ra.apply(service, action, "project", 10, [], {"100": " Box 2 ", "101": "Box 1", "102": "Shelf A"})
    assert outcome.changed == 2
    assert [_sample(service, nr).s_storage_loc for nr in (100, 101, 102)] == ["Box 2", "Box 1", "Shelf A"]
    assert outcome.notice() == "Sample Storage Location changed on 2 samples."

    # An emptied box clears the value.
    ra.apply(service, action, "project", 10, [], {"100": ""})
    assert _sample(service, 100).s_storage_loc is None


def test_edit_refuses_a_value_too_long_and_a_record_out_of_scope(service):
    action = ra.action_for("project", "sample.prep_storage_loc.edit")
    with pytest.raises(ValueError, match="at most 45"):
        ra.apply(service, action, "project", 10, [], {"100": "x" * 46})
    with pytest.raises(ValueError, match="Sample 200 is not in this selection"):
        ra.apply(service, action, "project", 10, [], {"200": "Box"})
    with pytest.raises(ValueError, match="Sample 102 is not in this selection"):
        ra.apply(service, action, "project", 10, [100], {"102": "Box"})
    assert _sample(service, 100).prep_storage_loc is None


def test_clear_storage_location(service):
    _sample(service, 100).prep_storage_loc = "Freezer 2"
    _sample(service, 101).prep_storage_loc = "  "
    service.session.commit()
    action = ra.action_for("project", "sample.prep_storage_loc.clear")
    preview = ra.plan(service, action, "project", 10, [])
    assert [(c.record.ref, c.old, c.new) for c in preview.changes] == [("100", "Freezer 2", "—")]
    assert preview.unchanged == 2
    ra.apply(service, action, "project", 10, [])
    assert _sample(service, 100).prep_storage_loc is None


def test_parse_values():
    assert ra.parse_values("") is None
    assert ra.parse_values('{"100": "Box 1"}') == {"100": "Box 1"}
    with pytest.raises(ValueError):
        ra.parse_values("[1, 2]")
    with pytest.raises(ValueError):
        ra.parse_values("{nope")

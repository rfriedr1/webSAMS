"""Swap target info (sams_web/target_swap.py, ADR-0008)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker

from sams_web import target_swap as ts
from sams_web.models import Base, Preparation, Project, Sample, Submitter, Target, calc_sample_table
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore

A = (100, 1, 1)
B = (200, 1, 2)


@pytest.fixture()
def service(tmp_path: Path) -> SamsService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, class_=Session)()
    setup_store = SetupStore(tmp_path / "setup.json")
    svc = SamsService(session, threshold_store=ThresholdStore(setup_store), setup_store=setup_store)

    session.add(Submitter(user_nr=1, last_name="Miller"))
    session.add(Project(project_nr=10, user_nr=1, project="P", in_date=date(2026, 1, 1), desired_date=date(2026, 4, 1)))
    for sample_nr in (100, 200):
        session.add(Sample(sample_nr=sample_nr, project_nr=10, user_label=f"S{sample_nr}", type="arch", material="bone", fraction="collagen"))
        session.add(Preparation(sample_nr=sample_nr, prep_nr=1))
    session.add(Target(
        sample_nr=100, prep_nr=1, target_nr=1, target_id="T-A",
        graph_batch="GB-1", reactor_nr="R1", graphitized=datetime(2026, 2, 1),
        conc_c=41.2, conc_n=14.9,
        magazine="MA260301", position="5", fm=0.98541, c14_age=118.4, calcset="MA260301", editallowed=2,
        target_comment="from A", stop=0,
    ))
    session.add(Target(
        sample_nr=200, prep_nr=1, target_nr=2, target_id="T-B",
        graph_batch="GB-2", reactor_nr="R2", graphitized=datetime(2026, 2, 2),
        conc_c=40.0, conc_n=14.9,
        magazine="MA260301", position="9", fm=0.5012, c14_age=5540.0, calcset="MA260301", editallowed=1,
        target_comment="from B", stop=1,
    ))
    session.add(Target(sample_nr=200, prep_nr=1, target_nr=1))
    session.flush()
    session.execute(insert(calc_sample_table), [
        {"calcset": "MA260301", "sample_nr": 100, "prep_nr": 1, "target_nr": 1, "type": "sample", "active": 1},
        {"calcset": "MA260301", "sample_nr": 200, "prep_nr": 1, "target_nr": 2, "type": "oxa2", "active": 1},
        {"calcset": "MA260215", "sample_nr": 100, "prep_nr": 1, "target_nr": 1, "type": "sample", "active": 0},
    ])
    session.commit()
    return svc


def _target(service: SamsService, key) -> Target:
    service.session.expire_all()
    return service.repo.get_target(*key)


def _calc_rows(service: SamsService, key) -> set[tuple[str, str]]:
    c = calc_sample_table.c
    rows = service.session.execute(
        select(c.calcset, c.type).where(c.sample_nr == key[0], c.prep_nr == key[1], c.target_nr == key[2])
    ).all()
    return {tuple(row) for row in rows}


def test_every_target_column_is_in_exactly_one_group_or_identity():
    columns = {attr.key for attr in Target.__mapper__.column_attrs}
    grouped = [name for group in ts.SWAP_GROUPS for name in group.fields]
    assert len(grouped) == len(set(grouped)), "a field is in two groups"
    assert set(grouped) | ts.IDENTITY_FIELDS == columns
    assert not set(grouped) & ts.IDENTITY_FIELDS


def test_parse_groups():
    assert ts.parse_groups(["comments", "graphitization"]) == ("graphitization", "comments")
    with pytest.raises(ValueError, match="at least one"):
        ts.parse_groups([])
    with pytest.raises(ValueError, match="Unknown group"):
        ts.parse_groups(["identity"])


def test_plan_compares_both_targets_and_warns_on_measurement(service):
    payload = ts.plan(service, A, B)
    assert payload["other"] == {"ref": "200.1.2", "href": "/samples/200/preparations/1/targets/2", "label": "S200"}
    groups = {g["key"]: g for g in payload["groups"]}
    assert list(groups) == ["graphitization", "ea", "measurement", "comments"]
    ea = {row["key"]: row for row in groups["ea"]["rows"]}
    assert ea["conc_c"]["this"] == "41.2" and ea["conc_c"]["other"] == "40.0"
    assert ea["conc_n"]["same"] is True
    assert groups["ea"]["differs"] == 1
    fm = next(row for row in groups["measurement"]["rows"] if row["key"] == "fm")
    assert (fm["this"], fm["other"]) == ("0.9854", "0.5012")  # the page's 4-decimal rule
    notes = [w["text"] for w in payload["warnings"]]
    assert all(w["group"] == "measurement" for w in payload["warnings"])
    assert any("100.1.1 is frozen" in text for text in notes)
    assert any("sample 100 and sample 200" in text and "BATS" in text for text in notes)
    assert any("2 of this target, 1 of target 200.1.2" in text for text in notes)


def test_swap_moves_only_the_ticked_groups(service):
    notice = ts.apply(service, A, B, ("graphitization", "comments"))
    assert notice == "Swapped Graphitization, Comments and Status with target 200.1.2."
    a, b = _target(service, A), _target(service, B)
    assert (a.graph_batch, a.reactor_nr, a.target_comment, a.stop) == ("GB-2", "R2", "from B", 1)
    assert (b.graph_batch, b.reactor_nr, b.target_comment, b.stop) == ("GB-1", "R1", "from A", 0)
    # Not ticked: stays.
    assert (a.conc_c, a.fm, a.position) == (41.2, 0.98541, "5")
    # Identity never moves.
    assert (a.sample_nr, a.target_nr, a.target_id) == (100, 1, "T-A")
    assert _calc_rows(service, A) == {("MA260301", "sample"), ("MA260215", "sample")}


def test_swapping_measurement_moves_results_and_bats_rows(service):
    ts.apply(service, A, B, ("measurement",))
    a, b = _target(service, A), _target(service, B)
    assert (a.fm, a.c14_age, a.position, a.editallowed) == (0.5012, 5540.0, "9", 1)
    assert (b.fm, b.c14_age, b.position, b.editallowed) == (0.98541, 118.4, "5", 2)
    assert _calc_rows(service, A) == {("MA260301", "oxa2")}
    assert _calc_rows(service, B) == {("MA260301", "sample"), ("MA260215", "sample")}
    assert _calc_rows(service, (-1, -1, -1)) == set()
    # Swapping back restores everything.
    ts.apply(service, A, B, ("measurement",))
    assert _target(service, A).fm == 0.98541
    assert _calc_rows(service, A) == {("MA260301", "sample"), ("MA260215", "sample")}


def test_swap_refuses_itself_and_a_missing_target(service):
    with pytest.raises(ValueError, match="itself"):
        ts.plan(service, A, A)
    with pytest.raises(ValueError, match="200.1.9 does not exist"):
        ts.apply(service, A, (200, 1, 9), ("graphitization",))
    assert _target(service, A).graph_batch == "GB-1"

"""Rename a magazine (sams_web/magazine_rename.py, ADR-0009)."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert, select
from sqlalchemy.orm import Session, sessionmaker

from sams_web import magazine_rename as mr
from sams_web.models import (
    Base,
    Preparation,
    Project,
    Sample,
    Submitter,
    Target,
    calc_set_table,
    magazine_table,
    measprog_table,
)
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore

PLANNED = "MA261113"
MEASURED = "MA261104"
EMPTY = "MB261110"


@pytest.fixture()
def service(tmp_path: Path) -> SamsService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, class_=Session)()
    setup_store = SetupStore(tmp_path / "setup.json")
    svc = SamsService(session, threshold_store=ThresholdStore(setup_store), setup_store=setup_store)

    session.add(Submitter(user_nr=1, last_name="Miller"))
    session.add(Project(project_nr=10, user_nr=1, project="P", in_date=date(2026, 1, 1), desired_date=date(2026, 4, 1)))
    session.add(Sample(sample_nr=100, project_nr=10, user_label="S100", type="arch", material="bone", fraction="collagen"))
    session.add(Preparation(sample_nr=100, prep_nr=1))
    # Planned: two targets in the sequence, nothing measured.
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=1, magazine=PLANNED, position="2", precis="1", editallowed=1))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=2, magazine=PLANNED, position="3", precis="1", editallowed=1))
    # Measured: results and a BATS calc set.
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=3, magazine=MEASURED, position="2", fm=0.5, calcset=MEASURED, editallowed=2))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=4, magazine=None))
    session.flush()
    session.execute(insert(magazine_table), [
        {"name": PLANNED, "last_changed": datetime(2026, 11, 10, 14, 0)},
        {"name": MEASURED, "last_changed": datetime(2026, 11, 7, 20, 0)},
        {"name": EMPTY, "last_changed": datetime(2026, 11, 10, 14, 48)},
    ])
    session.execute(insert(measprog_table), [
        {"magazine": PLANNED, "sequence": 1, "position": 2, "recno": 1, "prepdate": date(2026, 11, 10)},
        {"magazine": PLANNED, "sequence": 2, "position": 3, "recno": 2, "prepdate": date(2026, 11, 10)},
        {"magazine": MEASURED, "sequence": 1, "position": 2, "recno": 1, "prepdate": None},
    ])
    session.execute(insert(calc_set_table), [{"calcset": MEASURED, "magazine": MEASURED}])
    session.commit()
    return svc


def _where(service: SamsService) -> dict[str, list]:
    service.session.expire_all()
    s = service.session
    return {
        "targets": sorted(s.scalars(select(Target.magazine).where(Target.magazine.is_not(None))).all()),
        "sequence": sorted(s.scalars(select(measprog_table.c.magazine)).all()),
        "listed": sorted(s.scalars(select(magazine_table.c.name)).all()),
    }


def test_parse_new_name():
    assert mr.parse_new_name("  MA261114 ") == "MA261114"
    assert mr.parse_new_name("MA230505-1ST") == "MA230505-1ST"
    with pytest.raises(ValueError, match="Enter"):
        mr.parse_new_name("  ")
    with pytest.raises(ValueError, match="at most 12"):
        mr.parse_new_name("MA261114ICOS1")
    with pytest.raises(ValueError, match="no spaces"):
        mr.parse_new_name("MA 261114")


def test_lookup_finds_a_magazine_without_targets(service):
    # A magazine being planned may have no target yet; it is still a magazine.
    assert service.repo.resolve_existing_magazine("mb261110") == EMPTY
    assert EMPTY in service.repo.list_magazines()
    assert service.repo.list_magazines().count(PLANNED) == 1


def test_plan_lists_the_changes_and_checks_the_name(service):
    payload = mr.plan(service, PLANNED.lower(), "MA261114")
    assert payload["magazine"] == PLANNED
    assert payload["blocked"] == []
    assert {c["table"]: c["count"] for c in payload["changes"]} == {"measprog_t": 2, "target_t": 2, "magazine_t": 1}
    assert payload["new_name"] == "MA261114" and payload["error"] is None


@pytest.mark.parametrize(
    ("new_name", "message"),
    [
        (MEASURED.lower(), "Magazine MA261104 already exists"),
        (EMPTY, "Magazine MB261110 already exists"),
        ("ma261113", "current name"),
        ("MA 1", "no spaces"),
    ],
)
def test_plan_refuses_a_name_in_use(service, new_name, message):
    payload = mr.plan(service, PLANNED, new_name)
    assert payload["new_name"] is None
    assert message in payload["error"]


def test_a_measured_magazine_is_refused(service):
    payload = mr.plan(service, MEASURED, "MA261199")
    assert payload["new_name"] is None
    assert any("1 of its targets has measurement results" in reason for reason in payload["blocked"])
    assert any("calc set MA261104" in reason for reason in payload["blocked"])
    with pytest.raises(ValueError, match="was measured"):
        mr.apply(service, MEASURED, "MA261199")
    assert _where(service)["targets"].count(MEASURED) == 1


def test_a_calc_set_alone_blocks(service):
    service.session.execute(insert(calc_set_table), [{"calcset": PLANNED + "_1", "magazine": PLANNED}])
    service.session.commit()
    assert mr.plan(service, PLANNED)["blocked"] == ["BATS has evaluated it (calc set MA261113_1)."]


def test_rename_writes_every_table(service):
    renamed, notice = mr.apply(service, PLANNED, " MA261114 ")
    assert renamed == "MA261114"
    assert notice == "Renamed magazine MA261113 to MA261114 (2 targets, 2 sequence positions)."
    where = _where(service)
    assert where["targets"] == ["MA261104", "MA261114", "MA261114"]
    assert where["sequence"] == ["MA261104", "MA261114", "MA261114"]
    assert where["listed"] == ["MA261104", "MA261114", "MB261110"]


def test_rename_after_the_triggers_added_the_new_name(service):
    """On the live database, triggers on measprog_t / target_t REPLACE the new
    name into magazine_t during the update; the old row must then go."""
    service.session.execute(insert(magazine_table), [{"name": "MA261114", "last_changed": datetime(2026, 11, 10)}])
    service.repo.rename_magazine(PLANNED, "MA261114")
    service.session.commit()
    assert _where(service)["listed"] == ["MA261104", "MA261114", "MB261110"]


def test_rename_an_empty_magazine(service):
    renamed, notice = mr.apply(service, EMPTY, "MB261111")
    assert renamed == "MB261111"
    assert notice.endswith("(0 targets, 0 sequence positions).")
    assert "MB261111" in _where(service)["listed"]
    assert EMPTY not in _where(service)["listed"]


def test_unknown_magazine(service):
    with pytest.raises(ValueError, match="does not exist"):
        mr.plan(service, "XX000000")

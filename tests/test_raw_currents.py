"""Fetch LE/HE currents from the raw AMS databases (sams_web/raw_currents.py,
ADR-0011). The raw databases are replaced by a stub of the repository call;
the point of most tests is what happens when they cannot be read."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sams_web import raw_currents as rc
from sams_web.dependencies import get_service
from sams_web.main import app
from sams_web.models import Base, Preparation, Project, Sample, Submitter, Target
from sams_web.repositories import AMS_RAW_SYSTEMS, RawDataError, SamsRepository
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore

MB = "MB261120"
MA = "MA261120"
OTHER = "SE261120"
SAMS_WEB = Path(__file__).resolve().parents[1] / "sams_web"


@pytest.fixture()
def service(tmp_path: Path) -> SamsService:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,  # routes run in a worker thread
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, class_=Session)()
    setup_store = SetupStore(tmp_path / "setup.json")
    svc = SamsService(session, threshold_store=ThresholdStore(setup_store), setup_store=setup_store)
    session.add(Submitter(user_nr=1, last_name="Miller"))
    session.add(Project(project_nr=10, user_nr=1, project="P", in_date=date(2026, 1, 1), desired_date=date(2026, 4, 1)))
    session.add(Sample(sample_nr=100, project_nr=10, user_label="S100", type="arch", material="bone", fraction="collagen"))
    session.add(Preparation(sample_nr=100, prep_nr=1))
    # 1: nothing stored → new   2: stored, raw differs → replaced
    # 3: stored = raw → same    4: raw empty / 0 → no raw data, value kept
    # 5: frozen in BATS, nothing stored → new (written anyway)
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=1, magazine=MB, position="1"))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=2, magazine=MB, position="2", le_curr=30.0, he_curr=9.0))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=3, magazine=MB, position="3", le_curr=31.25, he_curr=9.5))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=4, magazine=MB, position="4", le_curr=29.0, he_curr=8.0))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=5, magazine=MB, position="5", editallowed=2))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=6, magazine=OTHER, position="1"))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=7, magazine=MA, position="1", le_curr=20.0))
    session.commit()
    return svc


RAW_MB = [
    {"sample_nr": 100, "prep_nr": 1, "target_nr": 1, "raw_rows": 1, "le_curr": 31.234, "he_curr": 9.876},
    {"sample_nr": 100, "prep_nr": 1, "target_nr": 2, "raw_rows": 2, "le_curr": 32.0, "he_curr": 9.0},
    {"sample_nr": 100, "prep_nr": 1, "target_nr": 3, "raw_rows": 1, "le_curr": 31.25, "he_curr": 9.5},
    {"sample_nr": 100, "prep_nr": 1, "target_nr": 4, "raw_rows": 1, "le_curr": None, "he_curr": 0},
    {"sample_nr": 100, "prep_nr": 1, "target_nr": 5, "raw_rows": 1, "le_curr": 28.5, "he_curr": 7.25},
]


def _raw(service: SamsService, rows=None, error: RawDataError | None = None) -> list[str]:
    """Stub the one raw read; returns the list of magazines asked for."""
    asked: list[str] = []

    def read(magazine):
        asked.append(magazine)
        if error is not None:
            raise error
        return list(rows or [])

    service.repo.raw_currents_for_magazine = read
    return asked


def _stored(service: SamsService) -> dict[int, tuple]:
    service.session.expire_all()
    rows = service.session.execute(select(Target.target_nr, Target.le_curr, Target.he_curr)).all()
    return {nr: (le, he) for nr, le, he in rows}


# ---- Comparing ----------------------------------------------------------------

def test_plan_compares_stored_and_raw_values(service):
    _raw(service, RAW_MB)
    plan = rc.plan(service, MB.lower())
    assert plan["magazine"] == MB and plan["raw_db"] == "db_ac14"
    assert plan["problem"] is None and plan["refusal"] is None
    by_nr = {row["target_nr"]: row for row in plan["rows"]}
    assert by_nr[1]["status"] == "new" and by_nr[1]["writes"] == {"le_curr": 31.23, "he_curr": 9.88}
    assert by_nr[2]["status"] == "differs" and by_nr[2]["writes"] == {"le_curr": 32.0}
    assert by_nr[3]["status"] == "same" and by_nr[3]["writes"] == {}
    assert by_nr[4]["status"] == "no_raw" and by_nr[4]["writes"] == {}
    assert by_nr[5]["status"] == "new" and by_nr[5]["frozen"]
    assert plan["counts"] == {"new": 2, "differs": 1, "same": 1, "no_raw": 1}
    assert plan["writes"] == 3 and plan["frozen_writes"] == 1 and plan["several_rows"] == 1


def test_a_target_missing_from_the_raw_data_counts_as_no_raw_data(service):
    _raw(service, RAW_MB[:1])
    plan = rc.plan(service, MB)
    assert plan["counts"]["no_raw"] == 4
    assert plan["writes"] == 1


def test_prefix_picks_the_raw_database_and_others_are_refused(service):
    assert AMS_RAW_SYSTEMS == {"MA": "db_dc14", "MB": "db_ac14"}
    assert rc.raw_db_for("ma230505-1ST") == "db_dc14"
    asked = _raw(service, [])
    plan = rc.plan(service, OTHER)
    assert plan["refusal"] and "MA… (db_dc14)" in plan["refusal"]
    assert asked == []  # never asks a raw database it has no map for


def test_magazine_without_any_raw_data_is_refused(service):
    _raw(service, [])
    plan = rc.plan(service, MA)
    assert plan["raw_db"] == "db_dc14"
    assert "has currents in db_dc14 yet" in plan["refusal"]
    with pytest.raises(ValueError, match="Nothing was changed"):
        rc.apply(service, MA)


def test_unknown_magazine_is_an_error(service):
    with pytest.raises(ValueError, match="does not exist"):
        rc.plan(service, "MB999999")


# ---- Fetching -------------------------------------------------------------------

def test_apply_writes_only_new_and_differing_values(service):
    _raw(service, RAW_MB)
    notice = rc.apply(service, MB)
    assert "3 targets of magazine MB261120 from db_ac14" in notice
    assert "2 new, 1 replaced, 1 without raw data" in notice
    stored = _stored(service)
    assert stored[1] == (31.23, 9.88)
    assert stored[2] == (32.0, 9.0)
    assert stored[3] == (31.25, 9.5)
    assert stored[4] == (29.0, 8.0)  # empty / 0 raw values never clear a stored one
    assert stored[5] == (28.5, 7.25)  # frozen in BATS: written anyway
    assert stored[6] == (None, None) and stored[7] == (20.0, None)


def test_apply_on_an_up_to_date_magazine_changes_nothing(service):
    _raw(service, RAW_MB)
    rc.apply(service, MB)
    before = _stored(service)
    assert "already up to date" in rc.apply(service, MB)
    assert _stored(service) == before


def test_apply_reads_the_raw_data_again(service):
    _raw(service, RAW_MB)
    rc.plan(service, MB)
    _raw(service, [dict(RAW_MB[0], le_curr=40.0)])
    rc.apply(service, MB)
    assert _stored(service)[1] == (40.0, 9.88)


# ---- Raw databases unavailable: a message, never a change or a 500 --------------

@pytest.mark.parametrize(
    ("code", "title"),
    [
        (1305, "Not set up yet"),
        (1370, "Not set up for the app"),
        (1049, "db_ac14 is not available"),
        (1146, "db_ac14 is not available"),
        (1054, "db_ac14.workfinal has changed"),
        (1142, "No permission to read db_ac14"),
        (1449, "No permission to read db_ac14"),
        (1969, "db_ac14 is not answering"),
        (1205, "db_ac14 is not answering"),
        (2013, "database server is not reachable"),
        (None, "Reading the raw AMS data failed"),
        (9999, "Reading the raw AMS data failed"),
    ],
)
def test_each_failure_is_described_and_changes_nothing(service, code, title):
    before = _stored(service)
    _raw(service, error=RawDataError(code, "server said no"))
    plan = rc.plan(service, MB)
    assert title in plan["problem"]["title"]
    assert plan["problem"]["advice"] and plan["problem"]["detail"] == "server said no"
    assert plan["rows"] == [] and plan["writes"] == 0
    with pytest.raises(ValueError) as err:
        rc.apply(service, MB)
    assert title in str(err.value) and str(err.value).endswith("Nothing was changed.")
    assert _stored(service) == before


def test_repository_turns_a_database_error_into_raw_data_error(service):
    # SQLite does not know SET STATEMENT / CALL: a real driver error, which
    # must come back as RawDataError with the session still usable.
    repo = SamsRepository(service.session)
    with pytest.raises(RawDataError):
        repo.raw_currents_for_magazine(MB)
    assert service.session.scalar(select(Target.magazine).where(Target.target_nr == 1)) == MB


def test_the_raw_call_is_limited_in_time():
    assert SamsRepository.RAW_CALL_LOCK_SECONDS <= 10
    assert SamsRepository.RAW_CALL_MAX_SECONDS <= 30


def test_only_the_currents_action_reads_the_raw_databases():
    """No page, API or other workflow may depend on the raw databases."""
    users = sorted(
        str(path.relative_to(SAMS_WEB))
        for path in SAMS_WEB.rglob("*.py")
        if "raw_currents_for_magazine" in path.read_text(encoding="utf-8")
    )
    assert users == ["raw_currents.py", "repositories.py", "services.py"]
    callers = sorted(
        str(path.relative_to(SAMS_WEB))
        for path in SAMS_WEB.rglob("*.py")
        if re.search(r"\braw_currents\.(plan|apply)\(", path.read_text(encoding="utf-8"))
    )
    assert callers == ["routers/pages_search_lab_import.py"]
    calls = [
        str(path.relative_to(SAMS_WEB))
        for path in SAMS_WEB.rglob("*.py")
        if "RAW_CURRENTS_PROCEDURE}(" in path.read_text(encoding="utf-8")
    ]
    assert calls == ["repositories.py"]


# ---- Routes ----------------------------------------------------------------------------

def _client(service: SamsService) -> TestClient:
    service.list_waiting_for_meas = lambda include_standards=False: []
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app)


@pytest.fixture()
def cleanup_overrides():
    yield
    app.dependency_overrides.pop(get_service, None)


def test_analysis_page_never_asks_the_raw_database(service, cleanup_overrides):
    asked = _raw(service, error=RawDataError(1049, "Unknown database 'db_ac14'"))
    response = _client(service).get(f"/lab/analysis?magazine={MB}")
    assert response.status_code == 200
    assert asked == []
    assert "data-raw-currents-open" in response.text
    assert 'href="#action=fetch-currents"' in response.text


def test_preview_reports_a_problem_with_http_200(service, cleanup_overrides):
    _raw(service, error=RawDataError(1049, "Unknown database 'db_ac14'"))
    response = _client(service).get(f"/lab/analysis/magazine/currents/preview?magazine={MB}")
    assert response.status_code == 200
    assert response.json()["problem"]["title"] == "db_ac14 is not available"


def test_fetch_route_redirects_with_a_toast(service, cleanup_overrides):
    _raw(service, RAW_MB)
    client = _client(service)
    response = client.post("/lab/analysis/magazine/currents", data={"magazine": MB}, follow_redirects=False)
    assert response.status_code == 303 and "action_notice=" in response.headers["location"]
    _raw(service, error=RawDataError(1146, "Table 'db_ac14.workfinal' doesn't exist"))
    response = client.post("/lab/analysis/magazine/currents", data={"magazine": MB}, follow_redirects=False)
    assert response.status_code == 303 and "action_error=" in response.headers["location"]

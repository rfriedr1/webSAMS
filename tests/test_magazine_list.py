"""The magazine list on Lab → Analysis (sams_web/magazine_list.py): newest
change first, capped by Setup → Analysis, and the magazine field searching
all magazines by part of the name."""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sams_web import magazine_list as ml
from sams_web.dependencies import get_service
from sams_web.main import app
from sams_web.models import Base, Preparation, Project, Sample, Submitter, Target, magazine_table
from sams_web.services import SamsService
from sams_web.setup_handlers import handler_for
from sams_web.setup_sections import SETUP_SECTION_ANALYSIS
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore


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
    # MB261127ICOS: newest, 2 targets, none measured
    # MA261120:     1 of 2 measured
    # MB261110:     planned, no targets yet (only in magazine_t)
    # 130710:       from before magazine_t existed (no date), measured
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=1, magazine="MB261127ICOS", position="1"))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=2, magazine="MB261127ICOS", position="2"))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=3, magazine="MA261120", position="1", fm=0.5))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=4, magazine="MA261120", position="2"))
    session.add(Target(sample_nr=100, prep_nr=1, target_nr=5, magazine="130710", position="1", c14_age=1200))
    session.execute(
        magazine_table.insert(),
        [
            {"name": "MB261127ICOS", "last_changed": datetime(2026, 11, 27, 12, 20)},
            {"name": "MA261120", "last_changed": datetime(2026, 11, 25, 16, 2)},
            {"name": "MB261110", "last_changed": datetime(2026, 11, 10, 14, 48)},
        ],
    )
    session.commit()
    return svc


@pytest.fixture()
def cleanup_overrides():
    yield
    app.dependency_overrides.pop(get_service, None)


def _client(service: SamsService) -> TestClient:
    service.list_waiting_for_meas = lambda include_standards=False: []  # MySQL-only SQL
    app.dependency_overrides[get_service] = lambda: service
    return TestClient(app)


def _listed(html: str) -> list[str]:
    return re.findall(r'<span class="magazine-list-name">([^<]+)</span>', html)


# ---- Repository ---------------------------------------------------------------

def test_newest_change_first_and_undated_last(service):
    rows = service.list_recent_magazines(10)
    assert [r["magazine"] for r in rows] == ["MB261127ICOS", "MA261120", "MB261110", "130710"]
    counts = {r["magazine"]: (r["target_count"], int(r["measured_targets"])) for r in rows}
    assert counts == {"MB261127ICOS": (2, 0), "MA261120": (2, 1), "MB261110": (0, 0), "130710": (1, 1)}
    assert service.count_magazines() == 4


def test_limit_and_find(service):
    assert [r["magazine"] for r in service.list_recent_magazines(2)] == ["MB261127ICOS", "MA261120"]
    assert [r["magazine"] for r in service.list_recent_magazines(10, "icos")] == ["MB261127ICOS"]
    assert [r["magazine"] for r in service.list_recent_magazines(10, "2611")] == ["MB261127ICOS", "MA261120", "MB261110"]
    assert service.count_magazines("mb") == 2
    # Typed text is text, not a LIKE pattern.
    assert service.list_recent_magazines(10, "%") == []
    assert service.count_magazines("_") == 0


# ---- Settings -----------------------------------------------------------------

def test_limit_setting_defaults_clamps_and_validates(service):
    store = ml.AnalysisSettingsStore(service.setup_store)
    assert store.load() == {"magazine_limit": ml.DEFAULT_MAGAZINE_LIMIT}
    assert store.update({"magazine_limit": " 50 "}) == {"magazine_limit": 50}
    assert store.load() == {"magazine_limit": 50}
    for bad in ("", "abc", "2.5", str(ml.MIN_MAGAZINE_LIMIT - 1), str(ml.MAX_MAGAZINE_LIMIT + 1)):
        with pytest.raises(ValueError):
            store.update({"magazine_limit": bad})
    assert store.load() == {"magazine_limit": 50}
    service.setup_store.set_section(SETUP_SECTION_ANALYSIS, {"magazine_limit": 999999})
    assert store.load() == {"magazine_limit": ml.MAX_MAGAZINE_LIMIT}


def test_setup_handler_round_trip(service):
    handler = handler_for(SETUP_SECTION_ANALYSIS)
    assert handler.kind == "analysis"
    handler.save(service, handler.read_form({"magazine_limit": "120"}))
    assert handler.context(service)["magazine_limit"] == 120


def test_measured_text_says_the_state_in_words():
    assert ml.measured_text(0, 0) == "no targets yet"
    assert ml.measured_text(39, 0) == "39 targets, not measured"
    assert ml.measured_text(1, 0) == "1 target, not measured"
    assert ml.measured_text(39, 39) == "39 measured"
    assert ml.measured_text(39, 37) == "37 of 39 measured"


# ---- Page -----------------------------------------------------------------------

def test_page_lists_magazines_and_marks_the_open_one(service, cleanup_overrides):
    html = _client(service).get("/lab/analysis?magazine=MA261120").text
    assert _listed(html) == ["MB261127ICOS", "MA261120", "MB261110", "130710"]
    assert re.search(r'magazine-list-item is-partly is-current"\s+aria-current="page"', html)
    assert "1 of 2 measured" in html
    assert "2 targets in MA261120" in html
    assert 'href="/lab/analysis?magazine=MB261110#tbl-magazine-targets"' in html


def test_list_is_capped_by_the_setting_and_says_so(service, cleanup_overrides):
    ml.AnalysisSettingsStore(service.setup_store).update({"magazine_limit": "10"})
    service.list_recent_magazines = lambda limit, find=None: SamsService.list_recent_magazines(service, 2, find)
    html = _client(service).get("/lab/analysis").text
    assert _listed(html) == ["MB261127ICOS", "MA261120"]
    assert "Latest 2 of 4" in html
    assert "search all 4" in html
    assert "Pick a magazine from the list" in html


def test_part_of_a_name_lists_the_matches_and_keeps_the_search(service, cleanup_overrides):
    html = _client(service).get("/lab/analysis?magazine=2611").text
    assert _listed(html) == ["MB261127ICOS", "MA261120", "MB261110"]
    assert "3 containing &ldquo;2611&rdquo;" in html
    assert 'href="/lab/analysis?magazine=MA261120&amp;find=2611#tbl-magazine-targets"' in html
    # Opening one from the filtered list keeps the filter.
    html = _client(service).get("/lab/analysis?magazine=MA261120&find=2611").text
    assert _listed(html) == ["MB261127ICOS", "MA261120", "MB261110"]
    assert "2 targets in MA261120" in html


def test_a_single_match_opens_it_and_none_says_so(service, cleanup_overrides):
    html = _client(service).get("/lab/analysis?magazine=icos").text
    assert "2 targets in MB261127ICOS" in html
    html = _client(service).get("/lab/analysis?magazine=zzz").text
    assert "No magazine name contains" in html
    html = _client(service).get("/lab/analysis?magazine=zzz&find=2611").text
    assert "There is no magazine zzz." in html


def test_standards_switch_survives_list_links(service, cleanup_overrides):
    html = _client(service).get("/lab/analysis?include_standards=true").text
    assert 'href="/lab/analysis?magazine=MA261120&amp;include_standards=true#tbl-magazine-targets"' in html

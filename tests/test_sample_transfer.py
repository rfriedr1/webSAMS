"""Transfer results from targets to samples (sams_web/sample_transfer.py,
ADR-0002): one ticked target is copied, several are a weighted FM mean."""

from __future__ import annotations

import json
import math
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sams_web import sample_transfer as st
from sams_web.dependencies import get_service
from sams_web.main import app
from sams_web.models import Base, Preparation, Project, Sample, Submitter, Target
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore

MAG = "MB261127"
OLD = "MB250101"


def _age(fm: float) -> float:
    return -8033 * math.log(fm)


def _target(sample_nr, prep_nr, target_nr, magazine, position, fm=None, fm_sig=None, **extra):
    values = dict(extra)
    if fm is not None:
        values.update(
            fm=fm, fm_sig=fm_sig, c14_age=_age(fm), c14_age_sig=8033 * fm_sig / fm, dc13=values.get("dc13", -20.0),
        )
    return Target(sample_nr=sample_nr, prep_nr=prep_nr, target_nr=target_nr, magazine=magazine, position=position, **values)


@pytest.fixture()
def service(tmp_path: Path) -> SamsService:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", future=True,
        connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, class_=Session)()
    setup_store = SetupStore(tmp_path / "setup.json")
    svc = SamsService(session, threshold_store=ThresholdStore(setup_store), setup_store=setup_store)
    session.add(Submitter(user_nr=1, last_name="Miller"))
    session.add(Project(project_nr=10, user_nr=1, project="P", in_date=date(2026, 1, 1), desired_date=date(2026, 4, 1)))

    def sample(nr, **values):
        session.add(Sample(sample_nr=nr, project_nr=10, user_label=f"S{nr}", type=values.pop("type", "arch"),
                           material="bone", fraction="collagen", **values))
        session.add(Preparation(sample_nr=nr, prep_nr=1))
        session.add(Preparation(sample_nr=nr, prep_nr=2))

    # 20001: one measured target, nothing stored → new (cal ranges copied)
    sample(20001)
    session.add(_target(20001, 1, 1, MAG, "3", 0.5, 0.002, cal1s_min=5600, cal1s_max=5700, cal2s_min=5500, cal2s_max=5800))
    # 20002: one measured target, the same result stored → same
    fm = 0.8
    sample(20002, c14_age=_age(fm), c14_age_sig=8033 * 0.002 / fm, av_fm=fm, av_fm_sig=0.002, av_dc13=-20.0)
    session.add(_target(20002, 1, 1, MAG, "1", fm, 0.002))
    # 20003: measured here and earlier in another magazine → choose
    sample(20003, c14_age=1000.0, c14_age_sig=20.0, av_fm=0.88, av_fm_sig=0.002, cal1s_min=900, cal1s_max=950)
    session.add(_target(20003, 1, 1, OLD, "7", 0.300, 0.001))
    session.add(_target(20003, 2, 1, MAG, "2", 0.302, 0.002, stop=1))
    session.add(_target(20003, 2, 2, MAG, "4"))  # in the magazine, not measured yet
    # 20004: near background → the legacy limit age
    sample(20004)
    session.add(_target(20004, 1, 1, MAG, "5", 0.0006, 0.0004))
    # 20005: in the magazine, nothing measured yet
    sample(20005)
    session.add(_target(20005, 1, 1, MAG, "6"))
    # standards are never transferred
    sample(9000, type="oxa2")
    session.add(_target(9000, 1, 1, MAG, "8", 1.3, 0.003))
    sample(20006, type="C6")
    session.add(_target(20006, 1, 1, MAG, "9", 0.0026, 0.0001))
    session.commit()
    return svc


def _rows(payload):
    return {row["sample_nr"]: row for row in payload["rows"]}


# ---- Math -----------------------------------------------------------------------

def test_single_result_copies_the_target():
    out = st.single_result({"fm": 0.5, "fm_sig": 0.002, "c14_age": 5568.0, "c14_age_sig": 32.0, "dc13": -21.0, "cal1s_min": 1})
    assert out["values"]["c14_age"] == 5568.0 and out["values"]["av_fm"] == 0.5 and out["values"]["cal1s_min"] == 1
    assert out["limit"] is False and out["agreement"] is None


def test_limit_rule_matches_the_legacy_one():
    # FM < 2σ (σ at least 0.0005) → −8033·ln(FM + 2σ), rounded to 100, sigma 99999
    assert st.limit_age(0.0006, 0.0004) == round(-math.log(0.0006 + 0.001) * 8033 / 100) * 100
    assert st.limit_age(0.01, 0.001) is None
    out = st.single_result({"fm": 0.0006, "fm_sig": 0.0004, "c14_age": 59000.0, "c14_age_sig": 5000.0})
    assert out["limit"] and out["values"]["c14_age_sig"] == st.LIMIT_AGE_SIGMA


def test_mean_is_inverse_variance_weighted_and_clears_the_cal_ranges():
    out = st.mean_result([
        {"prep_nr": 1, "target_nr": 1, "fm": 0.300, "fm_sig": 0.001, "dc13": -20.0, "cal1s_min": 1},
        {"prep_nr": 2, "target_nr": 1, "fm": 0.302, "fm_sig": 0.002, "dc13": -22.0},
    ])
    v = out["values"]
    w1, w2 = 1 / 0.001**2, 1 / 0.002**2
    fm = (0.300 * w1 + 0.302 * w2) / (w1 + w2)
    assert v["av_fm"] == pytest.approx(fm)
    assert v["av_fm_sig"] == pytest.approx(1 / math.sqrt(w1 + w2))
    assert v["c14_age"] == pytest.approx(_age(fm))
    assert v["c14_age_sig"] == pytest.approx(8033 * v["av_fm_sig"] / fm)
    assert v["av_dc13"] == pytest.approx(-21.0)
    assert all(v[field] is None for field in st.CAL_FIELDS)
    assert out["agreement"]["ok"] and out["agreement"]["critical"] == 3.84


def test_disagreeing_targets_are_flagged_not_refused():
    out = st.mean_result([
        {"prep_nr": 1, "target_nr": 1, "fm": 0.30, "fm_sig": 0.001},
        {"prep_nr": 1, "target_nr": 2, "fm": 0.32, "fm_sig": 0.001},
    ])
    assert out["agreement"]["ok"] is False and out["values"]["av_fm"] == pytest.approx(0.31)


def test_a_target_without_sigma_cannot_be_averaged():
    with pytest.raises(ValueError, match="1.2"):
        st.mean_result([{"prep_nr": 1, "target_nr": 1, "fm": 0.3, "fm_sig": 0.001},
                        {"prep_nr": 1, "target_nr": 2, "fm": 0.3, "fm_sig": None}])


def test_parse_choices_refuses_anything_malformed():
    assert st.parse_choices('{"20003": ["1.1", "2.1", "1.1"]}') == {20003: ["1.1", "2.1"]}
    assert st.parse_choices("") == {}
    for bad in ("[1]", "{", '{"x": ["1.1"]}', '{"1": "1.1"}'):
        with pytest.raises(ValueError):
            st.parse_choices(bad)


# ---- Preview ----------------------------------------------------------------------

def test_preview_defaults(service):
    payload = st.plan(service, MAG)
    rows = _rows(payload)
    assert set(rows) == {20001, 20002, 20003, 20004, 20005}  # standards skipped
    assert payload["standards"] == 2
    assert rows[20001]["status"] == "new" and rows[20001]["chosen"] == ["1.1"]
    assert rows[20001]["result"]["cal1s_min"] == 5600
    assert rows[20002]["status"] == "same"
    assert rows[20003]["status"] == "choose" and rows[20003]["chosen"] == []
    assert rows[20004]["status"] == "new" and rows[20004]["limit"] is True
    assert rows[20005]["status"] == "not_measured"
    assert payload["writes"] == 2
    # ordered by position in this magazine
    assert [row["sample_nr"] for row in payload["rows"]] == [20002, 20003, 20001, 20004, 20005]


def test_preview_lists_all_targets_of_a_sample(service):
    targets = _rows(st.plan(service, MAG))[20003]["targets"]
    assert [(t["target_id"], t["in_magazine"], t["measured"], t["discarded"]) for t in targets] == [
        ("20003.1.1", False, True, False),
        ("20003.2.1", True, True, True),
        ("20003.2.2", True, False, False),
    ]


def test_choosing_several_targets_gives_a_mean(service):
    row = _rows(st.plan(service, MAG, json.dumps({"20003": ["1.1", "2.1"]})))[20003]
    assert row["mode"] == "mean" and row["status"] == "replaces"
    assert row["result"]["cal1s_min"] is None
    assert [t["chosen"] for t in row["targets"]] == [True, True, False]


def test_unticking_the_only_target_leaves_the_sample_alone(service):
    payload = st.plan(service, MAG, json.dumps({"20001": [], "20003": []}))
    rows = _rows(payload)
    assert rows[20001]["status"] == "skip"
    assert rows[20003]["status"] == "choose"  # several measured: still waiting


def test_bad_choices_are_refused(service):
    with pytest.raises(ValueError, match="not a target"):
        st.plan(service, MAG, json.dumps({"20003": ["3.1"]}))
    with pytest.raises(ValueError, match="not measured in magazine"):
        st.plan(service, MAG, json.dumps({"9000": ["1.1"]}))
    row = _rows(st.plan(service, MAG, json.dumps({"20003": ["2.2"]})))[20003]
    assert row["status"] == "invalid" and "no result" in row["message"]


def test_unknown_magazine_and_standards_only(service):
    with pytest.raises(ValueError, match="does not exist"):
        st.plan(service, "MB000000")
    service.session.add(_target(9000, 1, 2, "MB261128", "1", 1.3, 0.003))
    service.session.commit()
    assert "only standards" in st.plan(service, "MB261128")["refusal"]


# ---- Transfer ---------------------------------------------------------------------

def test_apply_writes_only_new_and_replaced_results(service):
    message = st.apply(service, MAG, json.dumps({"20001": ["1.1"], "20003": ["1.1", "2.1"], "20004": ["1.1"]}))
    assert "3 samples" in message and "1 as a mean" in message
    session = service.session
    s1, s2, s3, s4, s5 = (session.get(Sample, nr) for nr in (20001, 20002, 20003, 20004, 20005))
    assert s1.av_fm == 0.5 and s1.cal1s_min == 5600
    assert s3.cal1s_min is None and s3.av_fm == pytest.approx((0.300 * 4 + 0.302) / 5)
    assert s4.c14_age_sig == st.LIMIT_AGE_SIGMA
    assert s5.c14_age is None
    # a second run finds everything up to date
    again = st.plan(service, MAG, json.dumps({"20001": ["1.1"], "20003": ["1.1", "2.1"], "20004": ["1.1"]}))
    assert again["writes"] == 0 and again["counts"]["same"] == 4


def test_apply_with_nothing_ticked_changes_nothing(service):
    service.session.query(Sample).filter(Sample.sample_nr == 20002).update({"c14_age": None})
    service.session.commit()
    with pytest.raises(ValueError, match="Nothing was changed"):
        st.apply(service, MAG, json.dumps({"20001": [], "20002": [], "20004": []}))
    assert service.session.get(Sample, 20001).c14_age is None


# ---- Routes ----------------------------------------------------------------------

@pytest.fixture()
def client(service):
    service.list_waiting_for_meas = lambda include_standards=False: []
    app.dependency_overrides[get_service] = lambda: service
    yield TestClient(app)
    app.dependency_overrides.pop(get_service, None)


def test_analysis_page_offers_the_transfer(client):
    response = client.get(f"/lab/analysis?magazine={MAG}")
    assert response.status_code == 200
    assert "data-sample-transfer-open" in response.text
    assert 'href="#action=transfer-results"' in response.text


def test_preview_route(client):
    response = client.get(f"/lab/analysis/magazine/transfer/preview?magazine={MAG}")
    assert response.status_code == 200 and response.json()["writes"] == 2
    bad = client.get(f"/lab/analysis/magazine/transfer/preview?magazine={MAG}&choices=%7B")
    assert bad.status_code == 422 and "error" in bad.json()


def test_transfer_route_redirects_with_a_toast(client, service):
    response = client.post("/lab/analysis/magazine/transfer",
                           data={"magazine": MAG, "choices": json.dumps({"20001": ["1.1"]})}, follow_redirects=False)
    assert response.status_code == 303 and "action_notice=" in response.headers["location"]
    response = client.post("/lab/analysis/magazine/transfer",
                           data={"magazine": MAG, "choices": json.dumps({"20003": ["9.9"]})}, follow_redirects=False)
    assert response.status_code == 303 and "action_error=" in response.headers["location"]

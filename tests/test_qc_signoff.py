"""Generic QC sign-off engine, exercised with the EA-check subject and with a
tiny fake subject that proves the engine knows nothing EA-specific."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sams_web import qc_signoff
from sams_web.dependencies import get_service
from sams_web.ea_checks import EaCheckLog, summarize, settings_from_raw, DEFAULT_SETTINGS
from sams_web.lab_staff import LabStaffStore
from sams_web.main import app
from sams_web.models import Base, QcSignoffItem
from sams_web.qc_signoff import QcSignoffs, SignoffItem, SignoffSubject
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore

T0 = datetime(2026, 10, 6, 8, 0)
KEY = "ea1|acetanilide"


@pytest.fixture
def service(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, class_=Session, autoflush=False)()
    store = SetupStore(tmp_path / "setup.json", seed_path=None)
    LabStaffStore(store).update({"names": ["Leni", "Ronny"], "roles": ["staff", "signer"]})
    yield SamsService(session, threshold_store=ThresholdStore(store), setup_store=store)
    session.close()


def seed_checks(service, count=5, fail_index=None):
    ids = []
    for i in range(count):
        when = T0 + timedelta(days=i)
        failing = i == fail_index
        outcome = EaCheckLog(service, now=when).record(
            {"ea": "ea1", "value_c": "80" if failing else f"{71.6 + i * 0.1:.1f}", "value_n": "10.5",
             "operator": "Leni", "comment": "leak" if failing else ""}
        )
        assert outcome.success, outcome.error
        ids.append(outcome.check.id)
    return ids


def sign(service, period_to, **overrides):
    args = {"subject_type": "ea_check", "subject_key": KEY, "period_to": period_to,
            "signer": "Ronny", "verdict": "accepted", "comment": ""}
    args.update(overrides)
    return QcSignoffs(service, now=T0 + timedelta(days=30)).sign(**args)


def test_signs_exactly_the_unsigned_set_up_to_period_to(service):
    ids = seed_checks(service, 5, fail_index=2)
    cutoff = (T0 + timedelta(days=3)).isoformat()  # 4 checks reviewed; the 5th came later
    outcome = sign(service, cutoff)
    assert outcome.success, outcome.error
    signoff = outcome.signoff
    assert signoff.n_items == 4 and signoff.n_flagged == 1
    assert sorted(QcSignoffs(service).repo.list_qc_signoff_item_refs(signoff.id)) == sorted(str(i) for i in ids[:4])
    # The stored snapshot is exactly what summarize gives for that set.
    checks = service.repo.list_ea_checks(ea="ea1", until=T0 + timedelta(days=3))
    expected = summarize(checks, settings_from_raw(DEFAULT_SETTINGS).standard("acetanilide"))
    assert json.loads(signoff.stats_json)["elements"] == json.loads(json.dumps(expected))["elements"]
    # The remaining check is the next unsigned set.
    rest = QcSignoffs(service).unsigned(qc_signoff.signoff_subjects()["ea_check"], KEY)
    assert [i.ref for i in rest] == [str(ids[4])]


def test_nothing_left_and_items_signed_once(service):
    seed_checks(service, 2)
    end = (T0 + timedelta(days=1)).isoformat()
    assert sign(service, end).success
    again = sign(service, end)
    assert not again.success and "Nothing left" in again.error
    assert service.session.query(QcSignoffItem).count() == 2


def test_only_signers_and_comment_rules(service):
    seed_checks(service, 1)
    end = T0.isoformat()
    assert "supervisor" in sign(service, end, signer="Leni").error
    assert "needs a comment" in sign(service, end, verdict="accepted_remarks").error
    assert "needs a comment" in sign(service, end, verdict="rejected").error
    assert sign(service, end, verdict="rejected", comment="EA leaking, service called").success


def test_no_signers_configured(service):
    LabStaffStore(service.setup_store).update({"names": ["Leni"], "roles": ["staff"]})
    seed_checks(service, 1)
    assert "Nobody may sign off" in sign(service, T0.isoformat()).error


def test_signed_check_cannot_be_voided(service):
    ids = seed_checks(service, 1)
    assert sign(service, T0.isoformat()).success
    outcome = EaCheckLog(service).void(ids[0], reason="oops", by="Leni")
    assert not outcome.success and "signed off" in outcome.error


class FakeSubject(SignoffSubject):
    subject_type = "fake"
    item_type = "fake_item"
    label = "Fake"

    def items(self, service, key, until=None):
        items = [SignoffItem(ref=f"r{i}", at=T0 + timedelta(hours=i), flagged=i == 1) for i in range(3)]
        return [i for i in items if until is None or i.at <= until]

    def summarize(self, service, key, items):
        return {"n": len(items)}


def test_engine_is_generic(service, monkeypatch):
    monkeypatch.setattr(qc_signoff, "signoff_subjects", lambda: {"fake": FakeSubject()})
    outcome = QcSignoffs(service, now=T0).sign(
        subject_type="fake", subject_key="anything", period_to="", signer="Ronny", verdict="accepted", comment=""
    )
    assert outcome.success
    assert outcome.signoff.n_items == 3 and outcome.signoff.n_flagged == 1
    assert json.loads(outcome.signoff.stats_json) == {"n": 3}
    history = QcSignoffs(service).history(subject_type="fake")
    assert history[0]["subject_label"] == "Fake" and history[0]["verdict_label"] == "Accepted"


def test_routes_sign_and_print(service):
    seed_checks(service, 3, fail_index=1)
    app.dependency_overrides[get_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.post(
            "/qc/signoffs",
            data={"subject_type": "ea_check", "subject_key": KEY, "period_to": (T0 + timedelta(days=2)).isoformat(),
                  "signer": "Ronny", "verdict": "accepted_remarks", "comment": "one leak, fixed", "next": "/lab/ea-checks"},
            follow_redirects=False,
        )
        assert response.status_code == 303 and "signoff_notice=" in response.headers["location"]
        page = client.get("/qc/signoffs/1")
        assert page.status_code == 200
        assert "Accepted with remarks" in page.text and "one leak, fixed" in page.text
        assert "Checks covered" in page.text
        assert client.get("/qc/signoffs/999").status_code == 404
    finally:
        app.dependency_overrides.pop(get_service, None)

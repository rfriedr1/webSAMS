"""EA checks: pure rules, the logging facade, settings and the routes.

In-memory SQLite with `Base.metadata.create_all` (as in test_service.py);
the settings file is a scratch file per test.
"""

from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sams_web.dependencies import get_service
from sams_web.ea_checks import (
    DEFAULT_SETTINGS,
    EaCheckLog,
    EaCheckSettingsStore,
    day_outcomes,
    evaluate,
    missed_workdays,
    parse_percent,
    passing_streak,
    settings_from_raw,
    summarize,
)
from sams_web.lab_staff import LabStaffStore
from sams_web.main import app
from sams_web.models import Base, EaCheck
from sams_web.services import SamsService
from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdStore

T0 = datetime(2026, 10, 6, 8, 0)  # a Tuesday


@pytest.fixture
def service(tmp_path):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, class_=Session, autoflush=False)()
    store = SetupStore(tmp_path / "setup.json", seed_path=None)
    LabStaffStore(store).update({"names": ["Leni", "Ronny"], "roles": ["staff", "signer"]})
    yield SamsService(session, threshold_store=ThresholdStore(store), setup_store=store)
    session.close()


def log_at(service, when: datetime) -> EaCheckLog:
    return EaCheckLog(service, now=when)


def record(service, when, c="71.8", n="10.5", ea="ea1", comment="", operator="Leni"):
    return log_at(service, when).record(
        {"ea": ea, "value_c": c, "value_n": n, "operator": operator, "comment": comment}
    )


# ---- pure rules -----------------------------------------------------------


def test_parse_percent_accepts_comma_and_point():
    assert parse_percent("71,84") == 71.84
    assert parse_percent(" 71.84 ") == 71.84
    assert parse_percent("") is None
    with pytest.raises(ValueError):
        parse_percent("abc")
    with pytest.raises(ValueError):
        parse_percent("120")


def test_evaluate_limits_are_inclusive():
    standard = settings_from_raw(DEFAULT_SETTINGS).standard("acetanilide")
    assert evaluate({"c": 64.0, "n": 11.4}, standard)[0] is True
    assert evaluate({"c": 63.99, "n": 10.4}, standard) == (False, {"c": False, "n": True})


def test_c_only_standard_needs_only_c():
    raw = {
        "standards": [{"key": "sucrose", "name": "Sucrose", "c": {"ref": 42.1, "min": 40, "max": 44}}],
        "instruments": [{"key": "ea1", "label": "EA 1", "standards": ["sucrose"]}],
    }
    standard = settings_from_raw(raw).standard("sucrose")
    assert [e.symbol for e in standard.elements] == ["c"]
    assert evaluate({"c": 42.0}, standard)[0] is True


def test_missed_workdays_skips_weekends():
    # Fri 2026-10-09 .. Tue 2026-10-13; checks Fri and Tue -> Mon missed only
    missed = missed_workdays([date(2026, 10, 9), date(2026, 10, 13)], date(2026, 10, 9), date(2026, 10, 13))
    assert missed == [date(2026, 10, 12)]


def test_passing_streak_uses_latest_attempt_and_ignores_weekends():
    outcomes = {date(2026, 10, 8): True, date(2026, 10, 9): True, date(2026, 10, 12): True}
    assert passing_streak(outcomes, date(2026, 10, 12)) == 3
    # today not yet checked: count from yesterday
    assert passing_streak(outcomes, date(2026, 10, 13)) == 3
    outcomes[date(2026, 10, 12)] = False
    assert passing_streak(outcomes, date(2026, 10, 12)) == 0


def test_day_outcomes_take_latest_non_voided_attempt():
    mk = lambda i, h, passed, voided=0: SimpleNamespace(  # noqa: E731
        id=i, checked_at=T0.replace(hour=h), passed=passed, voided=voided
    )
    assert day_outcomes([mk(1, 8, 1), mk(2, 13, 0)]) == {T0.date(): False}
    assert day_outcomes([mk(1, 8, 0), mk(2, 13, 1)]) == {T0.date(): True}
    assert day_outcomes([mk(1, 8, 1), mk(2, 13, 0, voided=1)]) == {T0.date(): True}


def test_summarize_matches_hand_computation():
    standard = settings_from_raw(DEFAULT_SETTINGS).standard("acetanilide")
    values = [71.5, 71.9, 72.3, 71.7]
    checks = [
        SimpleNamespace(
            id=i, checked_at=T0 + timedelta(days=i), conc_c=v, conc_n=10.4, passed=1, voided=0,
            c_ref=71.09, c_min=64.0, c_max=78.0, n_ref=10.36, n_min=9.4, n_max=11.4,
        )
        for i, v in enumerate(values)
    ]
    checks.append(SimpleNamespace(**{**vars(checks[0]), "id": 99, "conc_c": 10.0, "voided": 1}))
    stats = summarize(checks, standard)
    c = next(e for e in stats["elements"] if e["symbol"] == "c")
    assert stats["n"] == 4 and stats["n_failed"] == 0
    assert c["mean"] == round(statistics.fmean(values), 4)
    assert c["sd"] == round(statistics.stdev(values), 4)
    assert c["bias"] == round(statistics.fmean(values) - 71.09, 4)
    assert c["lo3"] == round(statistics.fmean(values) - 3 * statistics.stdev(values), 4)


# ---- logging facade ---------------------------------------------------------


def test_record_pass_and_fail_needs_comment(service):
    ok = record(service, T0, c="71,84")
    assert ok.success and ok.check.passed == 1 and ok.check.conc_c == 71.84
    assert ok.check.c_ref == 71.09 and ok.check.c_min == 64.0  # snapshot

    rejected = record(service, T0 + timedelta(hours=1), c="80")
    assert not rejected.success and "comment" in rejected.error

    failed = record(service, T0 + timedelta(hours=1), c="80", comment="leak, re-run")
    assert failed.success and failed.check.passed == 0


def test_record_validates_operator_and_values(service):
    assert "Pick who" in record(service, T0, operator="").error
    assert "Lab Staff" in record(service, T0, operator="Stranger").error
    assert "first" in record(service, T0, n="").error
    assert "Unknown EA" in record(service, T0, ea="nope").error


def test_several_checks_per_day_status_follows_latest(service):
    record(service, T0)
    record(service, T0 + timedelta(hours=4), c="80", comment="drift")
    card = log_at(service, T0 + timedelta(hours=5)).strip_view()["cards"][0]
    assert card["state"] == "failed" and len(card["attempts"]) == 2

    record(service, T0 + timedelta(hours=6))
    card = log_at(service, T0 + timedelta(hours=7)).strip_view()["cards"][0]
    assert card["state"] == "passed" and len(card["attempts"]) == 3


def test_card_has_one_trend_per_certified_element(service):
    record(service, T0, c="71.5", n="10.3")
    record(service, T0 + timedelta(days=1), c="71.9", n="10.6")
    card = log_at(service, T0 + timedelta(days=1, hours=1)).strip_view()["cards"][0]
    sparks = {s["symbol"]: [p["v"] for p in s["points"]] for s in card["config"]["sparks"]}
    assert sparks == {"c": [71.5, 71.9], "n": [10.3, 10.6]}


def test_card_shows_no_trend_before_two_checks(service):
    record(service, T0)
    card = log_at(service, T0 + timedelta(hours=1)).strip_view()["cards"][0]
    assert card["config"]["sparks"] == []


def test_void_falls_back_to_previous_attempt(service):
    record(service, T0)
    bad = record(service, T0 + timedelta(hours=1), c="17.2", comment="typo")
    log = log_at(service, T0 + timedelta(hours=2))
    assert log.void(bad.check.id, reason="typo: 17.2 for 71.2", by="Leni").success
    card = log_at(service, T0 + timedelta(hours=2)).strip_view()["cards"][0]
    assert card["state"] == "passed" and len(card["attempts"]) == 1
    assert "reason" in log.void(1, reason="", by="Leni").error
    assert "already voided" in log.void(bad.check.id, reason="x", by="Leni").error


def test_system_warnings_name_systems_of_unchecked_eas(service):
    record(service, T0)  # ea1 passed, ea2 not checked
    log = log_at(service, T0 + timedelta(hours=1))
    warnings = log.system_warnings(log.strip_view())
    assert "age64.1" not in warnings
    assert warnings["mag"].endswith("not checked yet")


def test_stats_never_mix_standards(service):
    store = EaCheckSettingsStore(service.setup_store)
    raw = dict(DEFAULT_SETTINGS)
    raw["standards"] = DEFAULT_SETTINGS["standards"] + [
        {"key": "sulfa", "name": "Sulfanilamide", "c": {"ref": 41.84, "min": 39, "max": 44}, "n": {"ref": 16.27, "min": 15, "max": 17.5}}
    ]
    raw["instruments"] = [{**DEFAULT_SETTINGS["instruments"][0], "standards": ["acetanilide", "sulfa"]}]
    service.setup_store.set_section(store.section_key, raw)
    record(service, T0)
    log_at(service, T0 + timedelta(hours=1)).record(
        {"ea": "ea1", "standard": "sulfa", "value_c": "41.8", "value_n": "16.3", "operator": "Leni"}
    )
    view = log_at(service, T0 + timedelta(hours=2)).page_view(period="all")
    by_std = {s["standard"]: s for s in view["sections"]}
    assert by_std["acetanilide"]["stats"]["n"] == 1
    assert by_std["sulfa"]["stats"]["elements"][0]["mean"] == 41.8


def test_removing_a_used_standard_is_refused(service):
    store = EaCheckSettingsStore(service.setup_store)
    payload = {"std_key": [""], "inst_key": ["ea1"], "inst_standards": ["acetanilide"], "signoff_reminder_days": "31"}
    with pytest.raises(ValueError, match="has logged checks"):
        store.update(payload, standards_in_use={"acetanilide"})


def test_settings_editor_round_trip(service):
    store = EaCheckSettingsStore(service.setup_store)
    settings = store.update(
        {
            "std_key": ["acetanilide"], "std_name": ["Acetanilide"], "std_lot": ["B42"],
            "std_c_ref": ["71,09"], "std_c_min": ["64"], "std_c_max": ["78"], "std_c_step": ["0.1"],
            "std_n_ref": ["10.36"], "std_n_min": ["9.4"], "std_n_max": ["11.4"], "std_n_step": [""],
            "inst_key": ["ea1"], "inst_label": ["EA 1"], "inst_systems": ["age64.1, age64.2"],
            "inst_standards": ["acetanilide"], "signoff_reminder_days": "14",
        }
    )
    assert settings.standard("acetanilide").lot == "B42"
    assert settings.standard("acetanilide").element("c").ref == 71.09
    assert settings.instruments[0].systems == ("age64.1", "age64.2")
    assert settings.reminder_days == 14
    with pytest.raises(ValueError, match="min ≤ reference ≤ max"):
        store.update({"std_key": ["x"], "std_c_ref": ["90"], "std_c_min": ["64"], "std_c_max": ["78"]})


def test_missing_tables_degrade_gracefully(service):
    service.session.execute(text("DROP TABLE ea_check_t"))
    log = EaCheckLog(service)
    assert log.missing_tables == ["ea_check_t"]
    assert log.strip_view()["available"] is False
    assert not log.record({"ea": "ea1"}).success


# ---- routes -------------------------------------------------------------------


@pytest.fixture
def client(service):
    app.dependency_overrides[get_service] = lambda: service
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_post_redirects_back_with_notice(client, service):
    response = client.post(
        "/lab/ea-checks",
        data={"ea": "ea1", "value_c": "71.8", "value_n": "10.5", "operator": "Leni", "next": "/lab/ea-checks?period=all"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/lab/ea-checks?period=all&ea_check_notice=")
    assert service.session.query(EaCheck).count() == 1


def test_post_refuses_offsite_next(client):
    response = client.post(
        "/lab/ea-checks",
        data={"ea": "ea1", "value_c": "71.8", "value_n": "10.5", "operator": "Leni", "next": "//evil.example"},
        follow_redirects=False,
    )
    assert response.headers["location"].startswith("/lab/ea-checks?")


def test_post_error_comes_back_as_error_param(client):
    response = client.post(
        "/lab/ea-checks", data={"ea": "ea1", "value_c": "80", "value_n": "10.5", "operator": "Leni"},
        follow_redirects=False,
    )
    assert "ea_check_error=" in response.headers["location"]


def test_page_renders_strip_stats_and_history(client, service):
    record(service, datetime.now() - timedelta(days=1))
    page = client.get("/lab/ea-checks?period=all")
    assert page.status_code == 200
    html = page.text
    assert "EA checks today" in html and "Standard deviation (s)" in html
    assert "Review &amp; sign off" in html and "Sign-off history" in html


def test_api_lists_checks(client, service):
    record(service, T0)
    data = client.get("/api/ea-checks?ea=ea1").json()
    assert data["checks"][0]["conc_c"] == 71.8 and data["checks"][0]["passed"] is True


def test_summarize_uses_passed_checks_for_mean_and_s(service):
    for i, c in enumerate(["71.6", "71.8", "72.0"]):
        record(service, T0 + timedelta(days=i), c=c)
    record(service, T0 + timedelta(days=3), c="63.2", comment="ash finger, re-run")
    view = log_at(service, T0 + timedelta(days=4)).page_view(period="all")
    stats = view["sections"][0]["stats"]
    c = next(e for e in stats["elements"] if e["symbol"] == "c")
    assert stats["n"] == 4 and stats["n_failed"] == 1
    assert c["n"] == 3 and c["mean"] == 71.8 and c["sd"] == 0.2

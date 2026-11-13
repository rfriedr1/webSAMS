"""Confirmation e-mail copies: Cc / Bcc from Setup, shown and chosen per e-mail.

No database and no mail server: `smtplib.SMTP` is replaced by a recorder
and the route's service by a stub holding a scratch settings file.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sams_web.dependencies import get_service
from sams_web.main import app
from sams_web.routers import pages_import
from sams_web.sample_import import mailer
from sams_web.sample_import.mailer import (
    EmailError,
    RenderedEmail,
    build_confirmation,
    invalid_addresses,
    send_email,
    split_addresses,
)
from sams_web.setup_store import SetupStore

SETTINGS = {
    "smtp_host": "mail.example.org",
    "smtp_port": 25,
    "smtp_security": "none",
    "from_address": "lab@example.org",
    "from_name": "Lab",
    "cc": "boss@example.org",
    "bcc": "archive@example.org; records@example.org",
}


def test_split_addresses_accepts_commas_semicolons_and_lines_and_drops_repeats():
    assert split_addresses("a@x.org, b@x.org;c@x.org\nA@X.org") == ["a@x.org", "b@x.org", "c@x.org"]
    assert split_addresses(["a@x.org", "", None, "b@x.org a@x.org"]) == ["a@x.org", "b@x.org"]
    assert split_addresses(None) == []


def test_invalid_addresses_names_the_bad_ones():
    assert invalid_addresses(["a@x.org", "colleague", "b@x"]) == ["colleague", "b@x"]


def test_preview_lists_setup_copies_so_the_operator_sees_them():
    submitter = SimpleNamespace(first_name="Ada", last_name="Lovelace", email="ada@example.org")
    message = build_confirmation(
        template={"subject": "S", "body": "B"},
        settings=SETTINGS,
        submitter=submitter,
        project_nr=1,
        project_name="P",
        sample_nrs=[1],
    )
    shown = message.as_dict()
    assert shown["cc"] == ["boss@example.org"]
    assert shown["bcc"] == ["archive@example.org", "records@example.org"]


class _RecordingSMTP:
    sent: list = []

    def __init__(self, *_args, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def send_message(self, email, to_addrs=None):
        _RecordingSMTP.sent.append((email, to_addrs))


@pytest.fixture
def smtp(monkeypatch):
    _RecordingSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", _RecordingSMTP)
    return _RecordingSMTP


def test_bcc_goes_only_into_the_envelope(smtp):
    send_email(
        RenderedEmail(
            to_address="ada@example.org",
            subject="S",
            body="B",
            from_address="lab@example.org",
            cc="boss@example.org",
            bcc="archive@example.org",
        ),
        SETTINGS,
    )
    email, to_addrs = smtp.sent[0]
    assert email["To"] == "ada@example.org"
    assert email["Cc"] == "boss@example.org"
    assert email["Bcc"] is None
    assert to_addrs == ["ada@example.org", "boss@example.org", "archive@example.org"]


def test_a_mistyped_copy_is_refused_before_connecting(smtp):
    message = RenderedEmail(
        to_address="ada@example.org",
        subject="S",
        body="B",
        from_address="lab@example.org",
        bcc="colleague",
    )
    with pytest.raises(EmailError, match="Bcc: colleague"):
        send_email(message, SETTINGS)
    assert smtp.sent == []


@pytest.fixture
def client(tmp_path):
    store = SetupStore(tmp_path / "setup_data.json", seed_path=None)
    store.set_section("email_settings", dict(SETTINGS))
    app.dependency_overrides[get_service] = lambda: SimpleNamespace(setup_store=store)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_service, None)


def test_send_uses_the_copies_the_operator_left_ticked_plus_added_ones(client, monkeypatch):
    captured = []
    monkeypatch.setattr(pages_import, "send_email", lambda message, _settings: captured.append(message))
    res = client.post(
        "/samples/import/email/send",
        json={
            "to_address": "ada@example.org",
            # Setup's Cc unticked; one Bcc kept, a stand-in colleague added.
            "cc": [],
            "bcc": ["archive@example.org", "standin@example.org"],
            "subject": "S",
            "body": "B",
        },
    )
    assert res.status_code == 200
    assert res.json() == {
        "sent": True,
        "to_address": "ada@example.org",
        "cc": [],
        "bcc": ["archive@example.org", "standin@example.org"],
    }
    assert captured[0].cc == ""
    assert captured[0].bcc == "archive@example.org, standin@example.org"

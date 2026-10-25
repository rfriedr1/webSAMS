"""Setup page: every section renders, saves through its real form, and keeps
what was typed when a save is rejected.

The settings file is a scratch file per test, so these never touch the
lab's real `setup_data.json`, and no database is needed.
"""

from __future__ import annotations

import json
import re
from html import unescape

import pytest
from fastapi.testclient import TestClient

from sams_web.dependencies import get_setup_store
from sams_web.main import app
from sams_web.setup_sections import SETUP_SECTIONS
from sams_web.setup_store import SetupStore


@pytest.fixture
def store(tmp_path):
    return SetupStore(tmp_path / "setup_data.json", seed_path=None)


@pytest.fixture
def client(store):
    app.dependency_overrides[get_setup_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_setup_store, None)


def _saved(store):
    return json.loads(store.path.read_text(encoding="utf-8"))


def _post(client, key, data):
    return client.post(f"/setup/{key}", data=data, follow_redirects=False)


@pytest.mark.parametrize("section", SETUP_SECTIONS, ids=lambda s: s.key)
def test_every_section_renders_its_editor(client, section):
    page = client.get(f"/setup?section={section.key}")
    assert page.status_code == 200
    html = page.text
    assert section.title in html
    assert f'action="{section.form_action}"' in html
    # The fallback for a section without an editor must never show.
    assert "Section Prepared" not in html


def test_unknown_section_is_a_404(client):
    assert client.get("/setup?section=nope").status_code == 404
    assert _post(client, "nope", {}).status_code == 404


def test_standard_thresholds_round_trip(client, store):
    page = client.get("/setup?section=standard_inventory_thresholds").text
    names = sorted(set(re.findall(r'name="([a-z0-9_]+_(?:red_below|yellow_min|yellow_max|green_above))"', page)))
    assert names, "threshold inputs not rendered"
    form = {name: "4" for name in names}
    form[next(n for n in names if n.startswith("oxas_") and n.endswith("green_above"))] = "17"
    response = _post(client, "standard_inventory_thresholds", form)
    assert response.status_code == 303
    assert _saved(store)["standard_inventory_thresholds"]["oxas"]["green_above"] == 17


def test_graphitization_systems_round_trip_and_rejection(client, store):
    response = _post(client, "graphitization_systems", {"graphitization_systems_text": "mag\nage.1\n\nage.2"})
    assert response.status_code == 303
    assert _saved(store)["graphitization_systems"] == ["mag", "age.1", "age.2"]

    rejected = _post(client, "graphitization_systems", {"graphitization_systems_text": "mag\nbad name!"})
    assert rejected.status_code == 400
    assert "Invalid system" in unescape(rejected.text)
    assert "bad name!" in unescape(rejected.text)  # what was typed is kept
    assert _saved(store)["graphitization_systems"] == ["mag", "age.1", "age.2"]  # nothing written

    duplicate = _post(client, "graphitization_systems", {"graphitization_systems_text": "mag\nmag"})
    assert duplicate.status_code == 400 and "Duplicate" in unescape(duplicate.text)
    empty = _post(client, "graphitization_systems", {"graphitization_systems_text": "  \n"})
    assert empty.status_code == 400 and "At least one" in unescape(empty.text)


def test_lab_warning_thresholds_round_trip(client, store):
    page = client.get("/setup?section=lab_warning_thresholds").text
    keys = re.findall(r'id="numeric-threshold-([a-z0-9_]+)"', page)
    assert keys
    response = _post(client, "lab_warning_thresholds", {key: "123" for key in keys})
    assert response.status_code == 303
    assert all(_saved(store)["lab_warning_thresholds"][key] == 123 for key in keys)


def test_import_headings_round_trip(client, store):
    response = _post(
        client,
        "import_column_headings",
        {
            "heading_user_label": "Probenname\nSample ID",
            "custom_target": ["s_storage_loc"],
            "custom_label": ["Storage location"],
            "custom_headings": ["Lagerort"],
        },
    )
    assert response.status_code == 303
    saved = _saved(store)["import_column_headings"]
    assert saved["headings"]["user_label"] == ["Probenname", "Sample ID"]
    assert saved["custom"][0]["target"] == "s_storage_loc"
    assert saved["custom"][0]["headings"] == ["Lagerort"]
    page = client.get("/setup?section=import_column_headings").text
    assert "Lagerort" in page and "Probenname" in page


def test_email_round_trip_keeps_password_out_of_the_page(client, store):
    form = {
        "smtp_host": "mail.example.org",
        "smtp_port": "587",
        "smtp_security": "starttls",
        "smtp_user": "lab@example.org",
        "smtp_password": "s3cret-pw",
        "from_address": "lab@example.org",
        "from_name": "Lab",
        "reply_to": "",
        "bcc": "",
        "template_en_subject": "Received: {project_name}",
        "template_en_body": "Hello {submitter_name}",
    }
    assert _post(client, "email_settings", form).status_code == 303
    saved = _saved(store)["email_settings"]
    assert saved["smtp_host"] == "mail.example.org"
    assert saved["smtp_password"] == "s3cret-pw"
    assert saved["templates"]["en"]["subject"] == "Received: {project_name}"
    page = client.get("/setup?section=email_settings").text
    assert "s3cret-pw" not in page
    assert "mail.example.org" in page


def test_sample_photos_round_trip_and_rejection_keeps_typed_folder(client, store, tmp_path):
    folder = tmp_path / "photos"
    folder.mkdir()
    assert _post(client, "sample_photos", {"folder": str(folder)}).status_code == 303
    assert _saved(store)["sample_photos"]["folder"] == str(folder)

    rejected = _post(client, "sample_photos", {"folder": "relative/path"})
    assert rejected.status_code == 400
    assert 'value="relative/path"' in rejected.text
    assert _saved(store)["sample_photos"]["folder"] == str(folder)


def test_json_api_reads_and_writes_a_section(client, store):
    listed = client.get("/api/setup/sections").json()
    assert [s["key"] for s in listed] == [s.key for s in SETUP_SECTIONS]
    response = client.put("/api/setup/graphitization_systems", json={"items": ["mag", "x.1"]})
    assert response.status_code == 200
    assert response.json()["list_items"] == ["mag", "x.1"]
    assert client.get("/api/setup/graphitization_systems").json()["list_items"] == ["mag", "x.1"]
    assert client.put("/api/setup/graphitization_systems", json={"items": "mag"}).status_code == 400

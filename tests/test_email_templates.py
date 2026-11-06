"""Which confirmation-e-mail template the import wizard picks."""

from __future__ import annotations

import pytest

from sams_web.import_settings import EmailSettingsStore
from sams_web.setup_store import SetupStore


@pytest.fixture
def store(tmp_path) -> EmailSettingsStore:
    return EmailSettingsStore(SetupStore(tmp_path / "setup.json", seed_path=None))


@pytest.mark.parametrize("language", [None, "", "   "])
def test_missing_language_defaults_to_german(store, language):
    assert store.resolve_template_code(language) == ("de", "no_language")
    assert "Eingang" in store.template_for_language(language)["subject"]


@pytest.mark.parametrize("language,code", [("en", "en"), ("DE", "de"), ("english", "en")])
def test_submitter_language_is_used(store, language, code):
    assert store.resolve_template_code(language) == (code, "language")


def test_language_without_template_falls_back_to_english(store):
    assert store.resolve_template_code("fr") == ("en", "unsupported")


def test_operator_choice_wins_over_language(store):
    assert store.resolve_template_code("de", "en") == ("en", "chosen")
    assert store.resolve_template_code(None, "en") == ("en", "chosen")
    assert "received" in store.template_for_language("de", "en")["subject"]


def test_unknown_operator_choice_is_ignored(store):
    assert store.resolve_template_code(None, "xx") == ("de", "no_language")


def test_template_choices_lists_every_template(store):
    codes = {c["code"]: c["label"] for c in store.template_choices()}
    assert codes == {"en": "English", "de": "German"}

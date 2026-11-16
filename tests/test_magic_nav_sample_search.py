"""Magic Nav `s:<text>`: a shortcut to Search → Samples (no search of its own)."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from sams_web.magic_nav import (
    SampleNav,
    SearchNav,
    SubmitterNameNav,
    build_magic_nav_rules,
    nav_exists,
    nav_not_found_message,
    resolve_magic_identifier,
)


def _query(nav):
    parts = urlsplit(nav.target)
    return parts.path, {k: v[0] for k, v in parse_qs(parts.query).items()}


@pytest.mark.parametrize(
    ("raw", "phrase"),
    [
        ("s:mosaic", "mosaic"),
        ("S: Mosaic ", "Mosaic"),
        ("s :mosaic wall", "mosaic wall"),
        ("s:123", "123"),            # digits are label text here, not a number
        ("s:R-EVA 3521", "R-EVA 3521"),
        ("s:50% & more", "50% & more"),
    ],
)
def test_search_prefix_opens_search_for_samples(raw, phrase):
    nav = resolve_magic_identifier(raw)
    assert isinstance(nav, SearchNav)
    assert nav.phrase == phrase
    assert _query(nav) == ("/search", {"context": "samples", "phrase": phrase})


@pytest.mark.parametrize("raw", ["s", "s:", "s: ", "s mosaic", "s123", "smosaic"])
def test_colon_and_text_are_required(raw):
    assert not isinstance(resolve_magic_identifier(raw), SearchNav)


def test_other_forms_are_unchanged():
    assert isinstance(resolve_magic_identifier("sub:meier"), SubmitterNameNav)
    assert isinstance(resolve_magic_identifier("12345"), SampleNav)
    assert resolve_magic_identifier("x:mosaic") is None


def test_search_always_exists_and_is_in_the_help_rules():
    nav = resolve_magic_identifier("s:mosaic")
    assert nav_exists(nav, object()) is True  # never asks the service
    assert nav_not_found_message(nav) == ""
    assert any(rule["example"] == "s:mosaic" for rule in build_magic_nav_rules())

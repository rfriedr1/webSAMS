"""Magic Nav `sub:<last name>`: parser, repository matching, lookup route."""

from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sams_web.magic_nav import (
    ProjectNav,
    SubmitterNameNav,
    SubmitterNav,
    build_magic_nav_rules,
    nav_exists,
    nav_not_found_message,
    resolve_magic_identifier,
)
from sams_web.models import Base, Submitter
from sams_web.repositories import SamsRepository
from sams_web.routers.pages_users_projects import submitter_name_lookup


@pytest.mark.parametrize("raw", ["sub210", "sub:210", "sub 210", "SUB: 210", "sub-210"])
def test_number_forms_all_open_the_submitter(raw):
    nav = resolve_magic_identifier(raw)
    assert nav == SubmitterNav(target="/submitters/210", user_nr=210)


@pytest.mark.parametrize("raw", ["pr456", "pr:456", "pr 456"])
def test_project_number_forms(raw):
    assert resolve_magic_identifier(raw) == ProjectNav(target="/projects/456", project_nr=456)


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("sub:meier", "meier"),
        ("sub meier", "meier"),
        ("submeier", "meier"),
        ("sub:Häck", "Häck"),
        ("SUB: O'Brien", "O'Brien"),
        ("sub  van   der Berg ", "van der Berg"),
        ("sub:Müller-Lüdenscheidt", "Müller-Lüdenscheidt"),
        # Documented: the prefix always comes first, so this is `sub` + `otic`.
        ("subotic", "otic"),
    ],
)
def test_name_forms_keep_the_typed_name(raw, name):
    nav = resolve_magic_identifier(raw)
    assert isinstance(nav, SubmitterNameNav)
    assert nav.last_name == name
    assert urlsplit(nav.target).path == "/submitters/lookup"
    assert parse_qs(urlsplit(nav.target).query)["name"] == [name]


@pytest.mark.parametrize("raw", ["meier", "pr:meier", "sub", "sub:", "sub:12ab", "sub:_x"])
def test_not_a_name_lookup(raw):
    assert resolve_magic_identifier(raw) is None


def test_commands_still_win_over_the_prefix():
    nav = resolve_magic_identifier("/sub")
    assert nav is not None and nav.target == "/submitters"


def test_name_nav_dispatchers():
    class _Service:
        def submitter_name_exists(self, last_name):
            return last_name == "Meier"

    assert nav_exists(resolve_magic_identifier("sub:Meier"), _Service())
    assert not nav_exists(resolve_magic_identifier("sub:Nobody"), _Service())
    assert nav_not_found_message(resolve_magic_identifier("sub:Nobody")) == (
        'No submitter with last name "Nobody" was found.'
    )


def test_help_rules_use_the_colon_form():
    examples = {rule["example"] for rule in build_magic_nav_rules()}
    assert {"pr:123", "sub:123", "sub:meier"} <= examples


# ---- repository ---------------------------------------------------------


@pytest.fixture()
def repo():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, class_=Session)()
    session.add_all(
        [
            Submitter(user_nr=1, last_name="Roth", first_name="Anna"),
            Submitter(user_nr=2, last_name="Rothe", first_name="Ben"),
            Submitter(user_nr=3, last_name="Rothe", first_name="Ben", town="Kiel"),
            Submitter(user_nr=4, last_name=" Meier ", first_name="Hans"),
            Submitter(user_nr=5, last_name="Meier", first_name="Hans", town="Jena"),
            Submitter(user_nr=6, last_name="Obermaier"),
            Submitter(user_nr=7, last_name="Per_cent%"),
        ]
    )
    session.commit()
    yield SamsRepository(session)
    session.close()


def test_exact_match_wins_over_substring(repo):
    assert repo.find_submitter_nrs_by_last_name("roth") == [1]


def test_duplicates_of_one_person_all_returned(repo):
    assert repo.find_submitter_nrs_by_last_name("MEIER") == [4, 5]


def test_substring_only_without_exact_hit(repo):
    assert repo.find_submitter_nrs_by_last_name("rot") == [1, 2, 3]
    assert repo.find_submitter_nrs_by_last_name("maier") == [6]


def test_like_wildcards_are_literal(repo):
    assert repo.find_submitter_nrs_by_last_name("%") == [7]
    assert repo.find_submitter_nrs_by_last_name("_") == [7]
    assert repo.find_submitter_nrs_by_last_name("nobody") == []
    assert repo.find_submitter_nrs_by_last_name("   ") == []


# ---- lookup route --------------------------------------------------------


class _LookupService:
    def __init__(self, nrs):
        self.nrs = nrs

    def find_submitter_nrs_by_last_name(self, last_name):
        return self.nrs


def test_lookup_single_match_opens_the_submitter():
    response = submitter_name_lookup(name="Roth", service=_LookupService([1]))
    assert response.status_code == 303
    assert response.headers["location"] == "/submitters/1"


def test_lookup_several_matches_open_the_filtered_list():
    response = submitter_name_lookup(name="Häck", service=_LookupService([2, 3]))
    location = urlsplit(response.headers["location"])
    assert location.path == "/submitters"
    assert parse_qs(location.query) == {"q": ["Häck"]}


def test_lookup_no_match_returns_inline_error():
    response = submitter_name_lookup(name="Nobody", service=_LookupService([]))
    location = urlsplit(response.headers["location"])
    query = parse_qs(location.query)
    assert location.path == "/submitters"
    assert query["magic_identifier"] == ["sub:Nobody"]
    assert query["magic_error"] == ['No submitter with last name "Nobody" was found.']

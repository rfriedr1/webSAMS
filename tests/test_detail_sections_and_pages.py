from datetime import date

from fastapi.responses import RedirectResponse

from sams_web.models import Project, Sample, Target
from sams_web.routers.pages import (
    _append_magic_feedback,
    _resolve_magic_identifier,
    sample_detail_page,
)
from sams_web.viewmodels import detail_sections as ds


def test_magic_identifier_resolution_and_feedback():
    assert _resolve_magic_identifier("123") == ("sample", 123, "/samples/123")
    assert _resolve_magic_identifier("pr123") == ("project", 123, "/projects/123")
    assert _resolve_magic_identifier("usr210") == ("user", 210, "/users/210")
    assert _resolve_magic_identifier("n/a") is None

    feedback_url = _append_magic_feedback("/search", entered_value="pr999", error_message="Project #999 missing")
    assert "magic_identifier=pr999" in feedback_url
    assert "magic_error=Project+%23999+missing" in feedback_url


def test_legacy_sample_target_redirect_uses_from_target_query_keys():
    response = sample_detail_page(
        request=None,  # type: ignore[arg-type]
        sample_nr=501,
        prep=2,
        target=8,
        target_page=3,
        target_page_size=25,
        service=None,  # type: ignore[arg-type]
    )
    assert isinstance(response, RedirectResponse)
    location = response.headers["location"]
    assert "/samples/501/preparations/2/targets/8" in location
    assert "from_target_page=3" in location
    assert "from_target_page_size=25" in location


def test_sample_section_build_includes_project_dates_and_excludes_old_info():
    sample = Sample(
        sample_nr=1,
        project_nr=9,
        user_label="A-1",
        old_info="legacy",
        c14_age=100.6,
        c14_age_sig=2.4,
    )
    project = Project(
        project_nr=9,
        in_date=date(2026, 1, 1),
        desired_date=date(2026, 2, 1),
        out_date=date(2026, 3, 1),
    )

    sections = ds.build_sample_sections(sample, project=project)
    submission = next(section for section in sections if section["title"] == "Submission")
    submission_keys = {row["key"] for row in submission["rows"]}
    assert "project_in_date" in submission_keys
    assert "project_desired_date" in submission_keys
    assert "project_out_date" in submission_keys

    other = next(section for section in sections if section["title"] == "Other Analysis")
    other_keys = {row["key"] for row in other["rows"]}
    assert "old_info" not in other_keys


def test_target_results_rounding_and_no_other_section():
    target = Target(
        sample_nr=1,
        prep_nr=1,
        target_nr=1,
        fm=1.234567,
        fm_sig=0.987654,
        dc13=-21.98765,
        c14_age=1234.5,
        c14_age_sig=34.6,
        magazine="M1",
        position="P9",
        le_curr=10.2,
        he_curr=20.7,
    )

    sections = ds.build_target_sections(target)
    titles = [section["title"] for section in sections]
    assert "Other" not in titles

    results = next(section for section in sections if section["title"] == "Results")
    values = {row["key"]: row["value"] for row in results["rows"]}
    assert values["fm"] == "1.2346"
    assert values["fm_sig"] == "0.9877"
    assert values["dc13"] == "-21.9877"
    assert values["c14_age"] == 1235
    assert values["c14_age_sig"] == 35

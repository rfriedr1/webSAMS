"""Click-to-edit detail pages: what the server renders and saves.

The browser posts only the changed fields; `apply_detail_update` must
leave everything else as stored. The field macro renders editors only for
a user who may edit, and after a rejected save marks the stored value as
the initial one so the edits stay dirty.
"""

from __future__ import annotations

import re

from sams_web.detail_update import apply_detail_update
from sams_web.models import Submitter
from sams_web.routers.pages_shared import templates
from sams_web.viewmodels.detail_sections_user_project import SUBMITTER_DETAIL


class _Repo:
    def __init__(self, submitter: Submitter) -> None:
        self.submitter = submitter

    def get_submitter(self, user_nr: int) -> Submitter | None:
        return self.submitter if user_nr == self.submitter.user_nr else None

    @property
    def session(self):
        class _Session:
            def flush(self) -> None:
                pass

        return _Session()


def test_partial_post_leaves_other_fields_untouched():
    submitter = Submitter(user_nr=7, last_name="Meier", first_name="Anna", town="Mannheim", email="a@x.de")
    result = apply_detail_update(SUBMITTER_DETAIL, 7, {"user__town": "Heidelberg"}, _Repo(submitter))
    assert result.saved, result.field_errors
    assert submitter.town == "Heidelberg"
    assert (submitter.last_name, submitter.first_name, submitter.email) == ("Meier", "Anna", "a@x.de")


def test_blank_posted_field_clears_only_that_field():
    submitter = Submitter(user_nr=7, last_name="Meier", town="Mannheim")
    result = apply_detail_update(SUBMITTER_DETAIL, 7, {"user__town": ""}, _Repo(submitter))
    assert result.saved
    assert submitter.town is None
    assert submitter.last_name == "Meier"


def _render(can_edit: bool, overrides: dict[str, str] | None = None, read_only=()) -> str:
    macro = templates.env.from_string(
        '{% from "_detail_fields.html" import render_detail_sections %}'
        "{{ render_detail_sections(sections, entity='user', css_prefix='user', form_id='f',"
        " read_only_fields=read_only, editor_value_overrides=overrides, can_edit=can_edit) }}"
    )
    sections = [
        {
            "title": "Address",
            "layout": "column",
            "rows": [
                {"key": "town", "label": "Town", "kind": "text", "value": "Mannheim", "raw_value": "Mannheim"},
                {"key": "user_nr", "label": "User #", "kind": "text", "value": 7, "raw_value": 7},
            ],
        }
    ]
    return macro.render(sections=sections, overrides=overrides, can_edit=can_edit, read_only=read_only)


def test_view_only_user_gets_no_editors():
    html = _render(can_edit=False)
    assert "data-field-editor" not in html
    assert "detail-field-pencil" not in html
    assert "Mannheim" in html


def test_editor_rendered_except_for_read_only_fields():
    html = _render(can_edit=True, read_only=("user_nr",))
    assert html.count("data-field-editor") == 1
    assert 'name="user__town"' in html
    assert 'name="user__user_nr"' not in html


def test_rejected_save_keeps_stored_value_as_initial():
    html = _render(can_edit=True, overrides={"user__town": "Heidelberg"})
    town_input = re.search(r"<input[^>]*name=\"user__town\"[^>]*>", html, re.S).group(0)
    assert 'value="Heidelberg"' in town_input
    assert 'data-initial-value="Mannheim"' in town_input


def test_without_override_no_initial_attribute():
    html = _render(can_edit=True)
    assert "data-initial-value" not in html

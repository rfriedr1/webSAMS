"""One link rule for every list table, and the record shortcuts' hooks.

`table_cell` (templates/_table_macros.html) replaced four hand-written
if-chains that had drifted apart (one linked `target_id`, another
`user_last_name`). The quick-nav arrows carry `data-quick-nav` because the
keyboard shortcuts looked them up by a class that the redesign renamed.
"""

from sams_web.routers.pages_shared import templates
from sams_web.search import fk_based_link

ROW = {
    "sample_nr": 48211,
    "prep_nr": 1,
    "target_nr": 2,
    "target_id": "48211.1.2",
    "project_nr": 246,
    "project": "Mammoth",
    "user_nr": 573,
    "last_name": "Meier",
    "user_last_name": "Meier",
    "user_label": "<b>bone</b>",
}

TARGET_URL = "/samples/48211/preparations/1/targets/2"


def test_link_rule_covers_every_queue_column():
    assert fk_based_link("sample_nr", ROW) == "/samples/48211"
    assert fk_based_link("prep_nr", ROW) == "/samples/48211/preparations/1"
    assert fk_based_link("target_nr", ROW) == TARGET_URL
    assert fk_based_link("target_id", ROW) == TARGET_URL
    assert fk_based_link("project", ROW) == "/projects/246"
    assert fk_based_link("last_name", ROW) == "/submitters/573"
    assert fk_based_link("user_last_name", ROW) == "/submitters/573"
    assert fk_based_link("user_label", ROW) is None


def test_link_rule_needs_the_whole_key():
    assert fk_based_link("target_id", {"target_id": "x", "sample_nr": 1}) is None
    assert fk_based_link("project", {"project": "Mammoth"}) is None


def _render_cell(key, row, link_for=None):
    macros = templates.env.get_template("_table_macros.html").module
    return str(macros.table_cell(key, row, link_for)).strip()


def test_table_cell_links_and_escapes():
    assert _render_cell("target_id", ROW) == f'<a href="{TARGET_URL}" class="table-link">48211.1.2</a>'
    # Customer-supplied text is escaped, never rendered as markup.
    assert "<b>" not in _render_cell("user_label", ROW)


def test_table_cell_honours_a_context_link_rule():
    assert _render_cell("user_label", ROW, lambda key, row: "/custom") == (
        '<a href="/custom" class="table-link">&lt;b&gt;bone&lt;/b&gt;</a>'
    )


def test_quick_nav_arrows_carry_the_shortcut_hooks():
    chrome = templates.env.get_template("_detail_chrome.html").module
    html = str(
        chrome.render_detail_quick_nav(
            "sample", 5, 9, 9, "/samples/4", "/samples/6", "/samples/open", "sample_nr"
        )
    )
    assert 'href="/samples/4" class="detail-quick-nav-arrow" data-quick-nav="prev"' in html
    assert 'href="/samples/6" class="detail-quick-nav-arrow" data-quick-nav="next"' in html

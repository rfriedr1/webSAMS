"""The project page's sample table with preps and targets under each sample,
and the minified JS bundle that drives it."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime
from types import SimpleNamespace

import pytest

from sams_web.main import _JS_BUNDLE_FILES, _STATIC_DIR, _minify_js
from sams_web.viewmodels.detail_sections_user_project import PROJECT_SAMPLE_COLUMNS
from sams_web.viewmodels.project_sample_tree import build_sample_tree, child_row_layout


def _prep(sample_nr, prep_nr, **values):
    base = dict(batch=None, prep_start=None, prep_end=None, stop=0, prep_comment=None)
    return SimpleNamespace(sample_nr=sample_nr, prep_nr=prep_nr, **{**base, **values})


def _target(sample_nr, prep_nr, target_nr, **values):
    base = dict(
        graph_batch=None, graphitized=None, magazine=None, fm=None, dc13=None,
        c14_age=None, c14_age_sig=None, stop=0, target_comment=None,
    )
    return SimpleNamespace(sample_nr=sample_nr, prep_nr=prep_nr, target_nr=target_nr, **{**base, **values})


def test_tree_orders_preps_with_their_targets_and_keeps_orphans():
    tree = build_sample_tree(
        [10, 11],
        [_prep(10, 2), _prep(10, 1, batch="pb_1", prep_end=datetime(2026, 3, 4, 0, 0))],
        [
            _target(10, 2, 1),
            _target(10, 1, 2, c14_age=1490.4, c14_age_sig=14.6, fm=0.83004, stop=1),
            _target(10, 1, 1),
            _target(10, 9, 1),  # its preparation is missing
        ],
    )
    assert [row["ref"] for row in tree[10]] == ["1", "1.1", "1.2", "2", "2.1", "9.1"]
    assert tree[11] == []
    prep = tree[10][0]
    assert prep["url"] == "/samples/10/preparations/1"
    assert [(f["label"], f["value"]) for f in prep["facts"]] == [("Prep Batch", "pb_1"), ("Prep End", "2026-03-04")]
    target = tree[10][2]
    assert target["url"] == "/samples/10/preparations/1/targets/2"
    assert (target["c14_age"], target["c14_age_sig"]) == (1490, 15)
    assert {"key": "fm", "label": "FM", "value": "0.8300"} in target["facts"]
    assert target["discarded"] is True


def test_child_rows_fill_every_sample_column():
    layout = child_row_layout(PROJECT_SAMPLE_COLUMNS)
    assert sum(part["span"] for part in layout) == len(PROJECT_SAMPLE_COLUMNS)
    slots = [part["slot"] for part in layout]
    assert slots == ["ref", "facts", "c14_age", "c14_age_sig", "comment"]
    assert layout[1]["span"] == len(PROJECT_SAMPLE_COLUMNS) - 4
    # A second run of sample-only columns stays blank.
    assert child_row_layout(["sample_nr", "a", "b", "c14_age", "c", "user_comment"]) == [
        {"slot": "ref", "span": 1},
        {"slot": "facts", "span": 2},
        {"slot": "c14_age", "span": 1},
        {"slot": "blank", "span": 1},
        {"slot": "comment", "span": 1},
    ]


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", _JS_BUNDLE_FILES)
def test_minified_bundle_files_still_parse(name, tmp_path):
    """The bundler's minifier strips `/* */` without reading strings or
    regexes: a block comment after a regex holding `/*` (table-tools.js)
    swallowed the code between them and every table lost its toolbar."""
    out = tmp_path / "min.js"
    out.write_text(_minify_js((_STATIC_DIR / name).read_text(encoding="utf-8")), encoding="utf-8")
    result = subprocess.run(["node", "--check", str(out)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

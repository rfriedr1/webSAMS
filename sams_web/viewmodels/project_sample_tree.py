"""The project page's sample table as a tree: each sample row with its
preparations and their targets underneath, as on the sample page.

Pure: takes the ORM records, returns plain row dicts for the template, so
the grouping and formatting are testable without a database.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Any, Iterable

from sams_web.field_labels import field_label
from sams_web.viewmodels.detail_sections_common import (
    format_c14_integer,
    is_empty_display_value,
)
from sams_web.viewmodels.detail_sections_sample_lab import format_target_indicator

PROJECT_TREE_MAX_CHILD_ROWS = 3000
"""Above this many preparations + targets the table lists samples only.

Project 798 (*CO2 HD*) has ~17 000 samples and project 1 (standards) 4 200
targets on 12 samples; listing every prep and target would triple a page
that is already the heaviest record page. Those projects keep the plain
sample list and say why."""


def _text(value: Any) -> str | None:
    if is_empty_display_value(value):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    return text or None


def _facts(pairs: Iterable[tuple[str, Any]]) -> list[dict[str, str]]:
    """`[{label, value}]` for the non-empty values, labels from the registry."""
    facts = []
    for key, value in pairs:
        shown = _text(value)
        if shown is not None:
            facts.append({"key": key, "label": field_label(key), "value": shown})
    return facts


def _prep_row(sample_nr: int, prep: Any) -> dict[str, Any]:
    return {
        "kind": "prep",
        "url": f"/samples/{sample_nr}/preparations/{prep.prep_nr}",
        "ref": str(prep.prep_nr),
        "facts": _facts(
            (("batch", prep.batch), ("prep_start", prep.prep_start), ("prep_end", prep.prep_end))
        ),
        "discarded": prep.stop == 1,
        "c14_age": None,
        "c14_age_sig": None,
        "comment": _text(prep.prep_comment),
    }


def _target_row(sample_nr: int, target: Any) -> dict[str, Any]:
    return {
        "kind": "target",
        "url": f"/samples/{sample_nr}/preparations/{target.prep_nr}/targets/{target.target_nr}",
        "ref": f"{target.prep_nr}.{target.target_nr}",
        "facts": _facts(
            (
                ("graph_batch", target.graph_batch),
                ("graphitized", target.graphitized),
                ("magazine", target.magazine),
                ("fm", format_target_indicator("fm", target.fm)),
                ("dc13", format_target_indicator("dc13", target.dc13)),
            )
        ),
        "discarded": target.stop == 1,
        "c14_age": format_c14_integer(target.c14_age) if target.c14_age is not None else None,
        "c14_age_sig": format_c14_integer(target.c14_age_sig) if target.c14_age_sig is not None else None,
        "comment": _text(target.target_comment),
    }


def build_sample_tree(
    sample_nrs: Iterable[int],
    preparations: Iterable[Any],
    targets: Iterable[Any],
) -> dict[int, list[dict[str, Any]]]:
    """`sample_nr -> child rows`: each preparation followed by its targets,
    in prep / target order. A target whose preparation is missing is listed
    after the sample's preparations, as on the sample page."""
    preps_by_sample: dict[int, list[Any]] = defaultdict(list)
    for prep in preparations:
        preps_by_sample[prep.sample_nr].append(prep)
    targets_by_sample: dict[int, list[Any]] = defaultdict(list)
    for target in targets:
        targets_by_sample[target.sample_nr].append(target)

    tree: dict[int, list[dict[str, Any]]] = {}
    for sample_nr in sample_nrs:
        rows: list[dict[str, Any]] = []
        sample_targets = sorted(targets_by_sample.get(sample_nr, ()), key=lambda t: (t.prep_nr, t.target_nr))
        prep_nrs = set()
        for prep in sorted(preps_by_sample.get(sample_nr, ()), key=lambda p: p.prep_nr):
            prep_nrs.add(prep.prep_nr)
            rows.append(_prep_row(sample_nr, prep))
            rows.extend(_target_row(sample_nr, t) for t in sample_targets if t.prep_nr == prep.prep_nr)
        rows.extend(_target_row(sample_nr, t) for t in sample_targets if t.prep_nr not in prep_nrs)
        tree[sample_nr] = rows
    return tree


_CHILD_SLOTS = {"sample_nr": "ref", "c14_age": "c14_age", "c14_age_sig": "c14_age_sig", "user_comment": "comment"}


def child_row_layout(columns: Iterable[str]) -> list[dict[str, Any]]:
    """How a prep / target row fills the sample table's columns.

    The record link sits under Sample #, the age and its sigma under theirs,
    the prep / target comment under the comment. The first run of other
    (sample-only) columns becomes one cell with the record's facts; any
    later run stays blank. Derived from the column keys, so adding a sample
    column keeps the rows aligned."""
    layout: list[dict[str, Any]] = []
    for key in columns:
        slot = _CHILD_SLOTS.get(key)
        if slot is None:
            previous = layout[-1]["slot"] if layout else None
            if previous in {"facts", "blank"}:
                layout[-1]["span"] += 1
                continue
            slot = "blank" if any(part["slot"] == "facts" for part in layout) else "facts"
        layout.append({"slot": slot, "span": 1})
    return layout

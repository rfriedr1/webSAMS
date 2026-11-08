"""Standard inventory thresholds: one yellow range per standard, and every
stock count gets a colour."""

from __future__ import annotations

import json

import pytest

from sams_web.setup_store import SetupStore
from sams_web.thresholds import ThresholdRule, ThresholdStore, default_threshold_rules


@pytest.mark.parametrize(
    ("count", "status"),
    [(0, "critical"), (8, "critical"), (9, "warning"), (14, "warning"), (15, "good")],
)
def test_the_yellow_range_decides_every_colour(count, status):
    assert ThresholdRule(yellow_min=9, yellow_max=14).classify(count) == status


def test_no_count_is_left_without_a_colour():
    # The old four-number rule left 1 IAEA-C6 uncoloured (red below 1,
    # yellow from 2). Now it is red.
    rule = default_threshold_rules()["iaea_c6"]
    assert [rule.classify(n) for n in range(6)] == [
        "critical", "critical", "warning", "warning", "good", "good",
    ]


def _store(tmp_path, section):
    path = tmp_path / "setup_data.json"
    path.write_text(json.dumps({"standard_inventory_thresholds": section}), encoding="utf-8")
    return ThresholdStore(SetupStore(path, seed_path=None)), path


def test_a_stored_four_number_rule_keeps_its_yellow_range_and_drops_the_rest(tmp_path):
    old = {key: {"red_below": 1, "yellow_min": 2, "yellow_max": 3, "green_above": 3} for key in default_threshold_rules()}
    old["oxas"] = {"red_below": 9, "yellow_min": 9, "yellow_max": 14, "green_above": 14}
    store, path = _store(tmp_path, old)

    rules = store.load()

    assert rules["oxas"] == ThresholdRule(yellow_min=9, yellow_max=14)
    assert rules["iaea_c6"] == ThresholdRule(yellow_min=2, yellow_max=3)
    saved = json.loads(path.read_text(encoding="utf-8"))["standard_inventory_thresholds"]
    assert saved["oxas"] == {"yellow_min": 9, "yellow_max": 14}


def test_an_inverted_stored_range_falls_back_to_the_default(tmp_path):
    section = {key: {"yellow_min": 2, "yellow_max": 3} for key in default_threshold_rules()}
    section["blanks"] = {"yellow_min": 9, "yellow_max": 4}
    store, _ = _store(tmp_path, section)
    assert store.load()["blanks"] == default_threshold_rules()["blanks"]


def test_update_rejects_an_inverted_range(tmp_path):
    section = {key: {"yellow_min": 2, "yellow_max": 3} for key in default_threshold_rules()}
    store, _ = _store(tmp_path, section)
    payload = dict(section)
    payload["oxas"] = {"yellow_min": "15", "yellow_max": "14"}
    with pytest.raises(ValueError, match="Oxas"):
        store.update(payload)

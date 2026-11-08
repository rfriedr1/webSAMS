from datetime import date, datetime

from sams_web.routers.pages_dashboard_setup_help import build_dashboard_view, deadline_split

TODAY = date(2026, 11, 7)


def _data(**overrides):
    data = {
        "counts": {
            "planned": 50,
            "in_prep": 100,
            "waiting_for_graph": 25,
            "waiting_for_meas": 0,
            "waiting_express": 5,
        },
        "standards": {"oxas": 20, "blanks": 10, "pferde": 1, "iaea_c6": 0, "iaea_c7": 5, "iaea_c8": 5},
        "standard_statuses": {"oxas": "good", "pferde": "critical", "blanks": "warning"},
        "standard_thresholds": {
            "pferde": {"yellow_min": 3, "yellow_max": 6},
        },
        "tables": {
            "waiting_express": [{"sample_nr": 1, "user_nr": 7, "last_name": "Meier", "project_nr": 3}],
            "planned": [],
            "waiting_for_meas": [
                {"sample_nr": 1, "prep_nr": 1, "target_nr": 1, "target_id": "1.1.1", "magazine": "M1"}
            ],
        },
    }
    data.update(overrides)
    return data


def test_queue_bars_follow_the_lab_path_and_link_to_their_table():
    view = build_dashboard_view(_data())
    bars = view["queue_bars"]
    assert [bar["key"] for bar in bars] == [
        "planned", "to_prep_bone", "to_prep_tooth",
        "in_prep", "waiting_for_graph", "waiting_for_meas", "waiting_express",
    ]
    by_key = {bar["key"]: bar for bar in bars}
    # The bone / tooth queues are parts of To prep all, drawn under it.
    assert [by_key[k]["label"] for k in ("planned", "to_prep_bone", "to_prep_tooth")] == [
        "To prep all", "To prep bone", "To prep tooth",
    ]
    assert [bar["key"] for bar in bars if bar["subset"]] == ["to_prep_bone", "to_prep_tooth"]
    assert by_key["in_prep"]["value"] == 100
    assert by_key["waiting_express"]["label"] == "Express"
    assert by_key["planned"]["anchor"] == "tbl-planned"


def test_queue_tabs_keep_table_order_and_hide_helper_columns():
    tabs = build_dashboard_view(_data())["queue_tabs"]
    assert [tab["key"] for tab in tabs] == ["waiting_express", "planned", "waiting_for_meas"]
    express, planned, meas = tabs
    # Link-only columns are not shown; the cells still use them for links.
    assert express["columns"] == ["sample_nr", "last_name"]
    assert planned["columns"] == []
    assert meas["columns"] == ["target_id", "magazine"]
    assert express["anchor"] == "tbl-waiting-express"


def test_standard_bars_carry_status_tag_and_rule():
    view = build_dashboard_view(_data())
    bars = {bar["key"]: bar for bar in view["standard_bars"]}
    assert bars["pferde"]["status"] == "critical"
    assert bars["pferde"]["tag"] == "Low"
    assert bars["blanks"]["tag"] == "Getting low"
    assert bars["oxas"]["tag"] == ""
    assert bars["iaea_c6"]["status"] == "neutral"
    assert bars["pferde"]["rule_summary"] == "Red below 3 · Yellow 3–6 · Green above 6"
    assert view["standards_total"] == 41


def test_empty_counts_do_not_divide_by_zero():
    data = _data(counts={key: 0 for key in _data()["counts"]}, standards={})
    view = build_dashboard_view(data)
    assert all(bar["value"] == 0 for bar in view["queue_bars"])
    assert all(bar["value"] == 0 for bar in view["standard_bars"])


def test_standard_bar_is_full_only_at_the_first_green_count():
    rule = {"yellow_min": 9, "yellow_max": 14}
    data = _data(
        standards={"oxas": 11, "blanks": 30},
        standard_statuses={"oxas": "warning", "blanks": "good"},
        standard_thresholds={"oxas": rule, "blanks": {"yellow_min": 5, "yellow_max": 8}},
    )
    bars = {bar["key"]: bar for bar in build_dashboard_view(data)["standard_bars"]}
    oxas = bars["oxas"]
    # 11 Oxas are the second-largest stock but still yellow: the bar must
    # not look full. Green starts at 15, so that is the end of the scale.
    assert oxas["target"] == 15
    assert oxas["pct"] == 73.3
    assert oxas["zones"] == {"yellow_start": 60.0, "yellow_end": 100.0}
    # Above the green threshold the bar is full, never longer.
    assert bars["blanks"]["pct"] == 100.0
    # No rule: relative to the largest stock, no target shown.
    assert bars["pferde"]["target"] is None
    assert bars["pferde"]["zones"] is None


def test_deadline_split_counts_each_queue_item_once():
    rows = [
        {"sample_nr": 1, "target_nr": 1, "desired_date": date(2026, 11, 6)},  # late
        {"sample_nr": 1, "target_nr": 2, "desired_date": date(2026, 11, 6)},  # same sample
        {"sample_nr": 2, "desired_date": date(2026, 11, 7)},  # due today: not late
        {"sample_nr": 3, "desired_date": datetime(2026, 11, 21, 8, 0)},  # day 14: soon
        {"sample_nr": 4, "desired_date": date(2026, 11, 22)},  # later
        {"sample_nr": 5, "desired_date": None},
        {"sample_nr": 6, "desired_date": date(1899, 12, 30)},  # legacy sentinel
    ]
    assert deadline_split("waiting_for_graph", rows, TODAY) == {"late": 1, "soon": 2, "later": 1, "undated": 2}
    # Other queues count rows, as their counts do: two preparations of one
    # sample in prep are two items.
    in_prep = [
        {"sample_nr": 1, "prep_nr": 1, "desired_date": date(2026, 1, 1)},
        {"sample_nr": 1, "prep_nr": 2, "desired_date": date(2026, 1, 1)},
    ]
    assert deadline_split("in_prep", in_prep, TODAY)["late"] == 2


def test_queue_bar_is_the_whole_queue_split_by_deadline():
    tables = {
        "planned": [
            {"sample_nr": 1, "desired_date": date(2026, 10, 1)},
            {"sample_nr": 2, "desired_date": date(2026, 11, 10)},
            {"sample_nr": 3, "desired_date": date(2027, 2, 1)},
            {"sample_nr": 4, "desired_date": date(2027, 2, 1)},
        ],
    }
    view = build_dashboard_view(_data(tables=tables), today=TODAY)
    bars = {bar["key"]: bar for bar in view["queue_bars"]}
    planned = bars["planned"]
    # The number is still the queue's count; the bar is its composition.
    assert planned["value"] == 50
    assert planned["late"] == 1
    assert [(s["band"], s["count"], s["pct"]) for s in planned["segments"]] == [
        ("late", 1, 25.0), ("soon", 1, 25.0), ("later", 2, 50.0),
    ]
    assert "1 past desired date" in planned["title"]
    # A queue with no table rows draws no segments and no late tag.
    assert bars["in_prep"]["segments"] == [] and bars["in_prep"]["late"] == 0
    # The legend only names colours that appear.
    assert [item["band"] for item in view["deadline_legend"]] == ["late", "soon", "later"]

from sams_web.routers.pages_dashboard_setup_help import build_dashboard_view


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
            "pferde": {"red_below": 3, "yellow_min": 3, "yellow_max": 6, "green_above": 6},
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
        "planned", "in_prep", "waiting_for_graph", "waiting_for_meas", "waiting_express",
    ]
    by_key = {bar["key"]: bar for bar in bars}
    assert by_key["in_prep"]["pct"] == 100.0
    assert by_key["planned"]["pct"] == 50.0
    assert by_key["waiting_for_meas"]["pct"] == 0.0
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
    assert "Red below 3" in bars["pferde"]["rule_summary"]
    assert view["standards_total"] == 41


def test_empty_counts_do_not_divide_by_zero():
    data = _data(counts={key: 0 for key in _data()["counts"]}, standards={})
    view = build_dashboard_view(data)
    assert all(bar["pct"] == 0.0 for bar in view["queue_bars"])
    assert all(bar["value"] == 0 for bar in view["standard_bars"])

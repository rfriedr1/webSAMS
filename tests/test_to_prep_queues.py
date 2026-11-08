"""The To prep queues: To prep all (`planned`) and the same query narrowed
to one material (bone, tooth). No database: the SQL is checked as text and
the fetch is stubbed."""

from __future__ import annotations

from sams_web.repositories import TO_PREP_MATERIAL_QUEUES, SamsRepository


def test_the_material_queues_are_to_prep_all_plus_one_bound_filter():
    everything = SamsRepository._sql_planned(show_on_hold=False)
    by_material = SamsRepository._sql_planned(show_on_hold=False, by_material=True)
    assert ":material" not in everything
    # Same query, one extra condition, value bound rather than pasted in.
    assert by_material.replace(" AND sample_t.material = :material", "") == everything
    assert "'bone'" not in by_material and "'tooth'" not in by_material


def test_held_samples_follow_the_same_switch_in_every_queue():
    for by_material in (False, True):
        assert "not_tobedated = 1" in SamsRepository._sql_planned(show_on_hold=True, by_material=by_material)
        assert "not_tobedated = 0" in SamsRepository._sql_planned(show_on_hold=False, by_material=by_material)


def test_list_to_prep_queues_fetches_one_list_per_material():
    calls: list[tuple[str, dict | None]] = []
    repo = SamsRepository.__new__(SamsRepository)

    def fake_fetch(sql, params=None):
        calls.append((sql, params))
        material = (params or {}).get("material")
        return [{"sample_nr": 1, "material": material or "wood"}]

    repo._fetch_rows = fake_fetch
    queues = repo.list_to_prep_queues(show_on_hold=True)

    assert list(queues) == ["planned", "to_prep_bone", "to_prep_tooth"]
    assert TO_PREP_MATERIAL_QUEUES == {"to_prep_bone": "bone", "to_prep_tooth": "tooth"}
    assert [params for _sql, params in calls] == [None, {"material": "bone"}, {"material": "tooth"}]
    assert all("not_tobedated = 1" in sql for sql, _params in calls)

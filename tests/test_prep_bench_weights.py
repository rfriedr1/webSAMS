"""Weight End on the preparation bench: container full minus container empty."""

from types import SimpleNamespace

from sams_web.preparation_bench import _derive_weight_end


def _prep(**values):
    base = {"weight_end": None, "weight_medium": None, "weight_medium_2": None}
    base.update(values)
    return SimpleNamespace(**base)


def test_end_weight_is_full_minus_empty():
    updates = {"weight_medium": 4730.9, "weight_medium_2": 4786.2}
    derived = _derive_weight_end(updates, _prep())
    assert round(derived["weight_end"], 4) == 55.3


def test_typed_end_weight_is_kept():
    updates = {"weight_medium": 4730.9, "weight_medium_2": 4786.2, "weight_end": 50.0}
    assert _derive_weight_end(updates, _prep())["weight_end"] == 50.0


def test_needs_both_container_weights():
    assert "weight_end" not in _derive_weight_end({"weight_medium": 4730.9}, _prep())

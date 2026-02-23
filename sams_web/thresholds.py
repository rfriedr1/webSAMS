"""Persistent storage for standard threshold settings."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from sams_web.setup_sections import SETUP_SECTION_STANDARD_THRESHOLDS
from sams_web.setup_store import SetupStore


STANDARD_LABELS: tuple[tuple[str, str], ...] = (
    ("Oxas", "oxas"),
    ("Blanks", "blanks"),
    ("Pferde", "pferde"),
    ("IAEA-C6", "iaea_c6"),
    ("IAEA-C7", "iaea_c7"),
    ("IAEA-C8", "iaea_c8"),
)

THRESHOLD_FIELDS: tuple[tuple[str, str], ...] = (
    ("red_below", "Red if <"),
    ("yellow_min", "Yellow from"),
    ("yellow_max", "Yellow to"),
    ("green_above", "Green if >"),
)


@dataclass(frozen=True)
class ThresholdRule:
    red_below: int
    yellow_min: int
    yellow_max: int
    green_above: int

    def classify(self, value: int) -> str:
        if value < self.red_below:
            return "critical"
        if self.yellow_min <= value <= self.yellow_max:
            return "warning"
        if value > self.green_above:
            return "good"
        # Preserve Delphi behavior for uncovered values (e.g. value=1 for C6/C7/C8/Pferde).
        return "neutral"


def default_threshold_rules() -> dict[str, ThresholdRule]:
    return {
        "oxas": ThresholdRule(red_below=9, yellow_min=9, yellow_max=14, green_above=14),
        "blanks": ThresholdRule(red_below=5, yellow_min=5, yellow_max=8, green_above=8),
        "pferde": ThresholdRule(red_below=1, yellow_min=2, yellow_max=3, green_above=3),
        "iaea_c6": ThresholdRule(red_below=1, yellow_min=2, yellow_max=3, green_above=3),
        "iaea_c7": ThresholdRule(red_below=1, yellow_min=2, yellow_max=3, green_above=3),
        "iaea_c8": ThresholdRule(red_below=1, yellow_min=2, yellow_max=3, green_above=3),
    }


class ThresholdStore:
    def __init__(
        self,
        setup_store: SetupStore,
        section_key: str = SETUP_SECTION_STANDARD_THRESHOLDS,
    ) -> None:
        self.setup_store = setup_store
        self.section_key = section_key

    @property
    def path(self) -> Path:
        return self.setup_store.path

    def load(self) -> dict[str, ThresholdRule]:
        defaults = default_threshold_rules()
        payload, legacy_layout = self._extract_payload(defaults)
        if payload is None:
            self.save(defaults)
            return defaults

        parsed: dict[str, ThresholdRule] = {}
        repaired = False

        for key, fallback in defaults.items():
            value = payload.get(key)
            rule, changed = self._coerce_rule(value=value, fallback=fallback)
            parsed[key] = rule
            repaired = repaired or changed

        if set(payload.keys()) != set(defaults.keys()):
            repaired = True

        if repaired or legacy_layout:
            self.save(parsed)

        return parsed

    def save(self, rules: dict[str, ThresholdRule]) -> None:
        serializable = {key: asdict(rule) for key, rule in rules.items()}
        payload = self.setup_store.load_all()
        # Clean up legacy layout keys if they still exist at top-level.
        for key in serializable.keys():
            payload.pop(key, None)
        payload[self.section_key] = serializable
        self.setup_store.save_all(payload)

    def update(self, payload: Mapping[str, Mapping[str, Any]]) -> dict[str, ThresholdRule]:
        current = self.load()
        updated: dict[str, ThresholdRule] = {}

        for key in current.keys():
            row = payload.get(key)
            if row is None:
                raise ValueError(f"Missing threshold values for '{key}'.")
            updated[key] = ThresholdRule(
                red_below=self._to_non_negative_int(row.get("red_below"), f"{key}: red_below"),
                yellow_min=self._to_non_negative_int(row.get("yellow_min"), f"{key}: yellow_min"),
                yellow_max=self._to_non_negative_int(row.get("yellow_max"), f"{key}: yellow_max"),
                green_above=self._to_non_negative_int(row.get("green_above"), f"{key}: green_above"),
            )

        self.save(updated)
        return updated

    @staticmethod
    def as_payload(rules: dict[str, ThresholdRule]) -> dict[str, dict[str, int]]:
        return {key: asdict(rule) for key, rule in rules.items()}

    def _extract_payload(self, defaults: dict[str, ThresholdRule]) -> tuple[dict[str, Any] | None, bool]:
        raw = self.setup_store.load_all()
        payload = raw.get(self.section_key)
        legacy_layout = False

        if isinstance(payload, dict):
            return payload, legacy_layout

        # Backward compatibility for the legacy layout where threshold keys
        # lived directly at top level in the JSON file.
        if self._looks_like_legacy_payload(raw=raw, defaults=defaults):
            payload = raw
            legacy_layout = True

        return payload if isinstance(payload, dict) else None, legacy_layout

    @staticmethod
    def _looks_like_legacy_payload(raw: dict[str, Any], defaults: dict[str, ThresholdRule]) -> bool:
        default_keys = set(defaults.keys())
        raw_keys = set(raw.keys())
        if not default_keys.issubset(raw_keys):
            return False
        return all(isinstance(raw.get(key), dict) for key in default_keys)

    @staticmethod
    def _coerce_rule(value: Any, fallback: ThresholdRule) -> tuple[ThresholdRule, bool]:
        if not isinstance(value, dict):
            return fallback, True

        parsed_values: dict[str, int] = {}
        changed = False
        for field, _ in THRESHOLD_FIELDS:
            raw = value.get(field)
            if raw is None:
                parsed_values[field] = getattr(fallback, field)
                changed = True
                continue
            try:
                coerced = int(raw)
            except (TypeError, ValueError):
                parsed_values[field] = getattr(fallback, field)
                changed = True
                continue
            if coerced < 0:
                parsed_values[field] = getattr(fallback, field)
                changed = True
                continue
            parsed_values[field] = coerced

        return (
            ThresholdRule(
                red_below=parsed_values["red_below"],
                yellow_min=parsed_values["yellow_min"],
                yellow_max=parsed_values["yellow_max"],
                green_above=parsed_values["green_above"],
            ),
            changed,
        )

    @staticmethod
    def _to_non_negative_int(value: Any, field_name: str) -> int:
        try:
            parsed = int(str(value).strip())
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid integer for '{field_name}'.") from exc
        if parsed < 0:
            raise ValueError(f"Threshold '{field_name}' must be >= 0.")
        return parsed

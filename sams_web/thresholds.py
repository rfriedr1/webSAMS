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
STANDARD_LABEL_BY_KEY: dict[str, str] = {key: label for label, key in STANDARD_LABELS}

THRESHOLD_FIELDS: tuple[tuple[str, str], ...] = (
    ("yellow_min", "Yellow from"),
    ("yellow_max", "Yellow to"),
)

# Keys of the old four-number rule (Delphi). Red ended where yellow began
# and green began where yellow ended, so only the yellow range carries
# information; a stored rule with these keys is rewritten without them.
LEGACY_THRESHOLD_KEYS = ("red_below", "green_above")


@dataclass(frozen=True)
class ThresholdRule:
    """Stock status of one standard, from its yellow range alone: red
    below `yellow_min`, yellow from `yellow_min` to `yellow_max`, green
    above. Every count has a colour; there is no gap and no overlap.
    (The Delphi rule had four independent numbers, and a count that fell
    between them, such as 1 IAEA-C6 with red below 1 and yellow from 2,
    got no colour at all.)"""

    yellow_min: int
    yellow_max: int

    def classify(self, value: int) -> str:
        if value < self.yellow_min:
            return "critical"
        if value <= self.yellow_max:
            return "warning"
        return "good"


def default_threshold_rules() -> dict[str, ThresholdRule]:
    return {
        "oxas": ThresholdRule(yellow_min=9, yellow_max=14),
        "blanks": ThresholdRule(yellow_min=5, yellow_max=8),
        "pferde": ThresholdRule(yellow_min=2, yellow_max=3),
        "iaea_c6": ThresholdRule(yellow_min=2, yellow_max=3),
        "iaea_c7": ThresholdRule(yellow_min=2, yellow_max=3),
        "iaea_c8": ThresholdRule(yellow_min=2, yellow_max=3),
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
            label = STANDARD_LABEL_BY_KEY.get(key, key)
            yellow_min = self._to_non_negative_int(row.get("yellow_min"), f"{label}: Yellow from")
            yellow_max = self._to_non_negative_int(row.get("yellow_max"), f"{label}: Yellow to")
            if yellow_min > yellow_max:
                raise ValueError(
                    f"{label}: 'Yellow from' ({yellow_min}) must not be above 'Yellow to' ({yellow_max})."
                )
            updated[key] = ThresholdRule(yellow_min=yellow_min, yellow_max=yellow_max)

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

        if parsed_values["yellow_min"] > parsed_values["yellow_max"]:
            return fallback, True
        if any(key in value for key in LEGACY_THRESHOLD_KEYS):
            changed = True

        return (
            ThresholdRule(
                yellow_min=parsed_values["yellow_min"],
                yellow_max=parsed_values["yellow_max"],
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

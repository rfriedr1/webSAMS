"""Persistent storage for lab warning/quality thresholds.

These thresholds drive in-app warning highlights on detail pages
(e.g. red-tinted card + warning hint on a target's Total C value
when it falls below the configured minimum, or on a preparation's
Yield (%) when below 0.5%). They are intentionally separate from
`standard_inventory_thresholds`, which colour the dashboard standards
row.

The schema is a flat numeric dict — `{key: float | int}` — so adding
a new threshold is a one-line entry in `LAB_WARNING_THRESHOLD_FIELDS`.
Each field declares its `decimals` for display formatting and `step`
for the HTML number input. Values are stored as float in JSON; an
int-typed default with `decimals=0` round-trips as a Python int when
read back. The SetupStore section key is `lab_warning_thresholds`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sams_web.setup_store import SetupStore


SETUP_SECTION_LAB_WARNING_THRESHOLDS = "lab_warning_thresholds"


@dataclass(frozen=True)
class LabWarningThresholdField:
    key: str
    label: str
    description: str
    unit: str
    default: float
    decimals: int = 0
    step: float = 1.0

    def format(self, value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if self.decimals <= 0:
            return str(int(round(number)))
        return f"{number:.{self.decimals}f}"


LAB_WARNING_THRESHOLD_FIELDS: tuple[LabWarningThresholdField, ...] = (
    LabWarningThresholdField(
        key="target_total_c_ug_min",
        label="Target Total C minimum",
        description=(
            "Warn on a target's detail page when the calculated total carbon "
            "mass (from Weight Combustion × C %) falls below this value."
        ),
        unit="µg",
        default=500.0,
        decimals=0,
        step=1.0,
    ),
    LabWarningThresholdField(
        key="preparation_yield_percent_min",
        label="Preparation Yield minimum",
        description=(
            "Warn on a preparation's detail page when the calculated yield "
            "(end weight / start weight × 100) falls below this percentage."
        ),
        unit="%",
        default=0.5,
        decimals=1,
        step=0.1,
    ),
)


LAB_WARNING_THRESHOLD_FIELD_BY_KEY: dict[str, LabWarningThresholdField] = {
    field.key: field for field in LAB_WARNING_THRESHOLD_FIELDS
}


def default_lab_warning_thresholds() -> dict[str, float]:
    return {field.key: field.default for field in LAB_WARNING_THRESHOLD_FIELDS}


class LabWarningThresholdStore:
    def __init__(
        self,
        setup_store: SetupStore,
        section_key: str = SETUP_SECTION_LAB_WARNING_THRESHOLDS,
    ) -> None:
        self.setup_store = setup_store
        self.section_key = section_key

    @property
    def path(self) -> Path:
        return self.setup_store.path

    def load(self) -> dict[str, float]:
        defaults = default_lab_warning_thresholds()
        raw = self.setup_store.get_section(self.section_key, default=None)
        if not isinstance(raw, dict):
            self.save(defaults)
            return defaults

        parsed: dict[str, float] = {}
        repaired = False
        for field in LAB_WARNING_THRESHOLD_FIELDS:
            value = raw.get(field.key)
            try:
                coerced = float(value)
            except (TypeError, ValueError):
                parsed[field.key] = field.default
                repaired = True
                continue
            if coerced < 0:
                parsed[field.key] = field.default
                repaired = True
                continue
            parsed[field.key] = coerced

        if set(raw.keys()) != {f.key for f in LAB_WARNING_THRESHOLD_FIELDS}:
            repaired = True

        if repaired:
            self.save(parsed)
        return parsed

    def save(self, values: Mapping[str, float]) -> None:
        clean = {field.key: float(values.get(field.key, field.default)) for field in LAB_WARNING_THRESHOLD_FIELDS}
        self.setup_store.set_section(self.section_key, clean)

    def update(self, payload: Mapping[str, Any]) -> dict[str, float]:
        updated: dict[str, float] = {}
        for field in LAB_WARNING_THRESHOLD_FIELDS:
            raw = payload.get(field.key)
            if raw is None or (isinstance(raw, str) and raw.strip() == ""):
                raise ValueError(f"Missing value for '{field.label}'.")
            try:
                parsed = float(str(raw).strip())
            except (TypeError, ValueError) as exc:
                raise ValueError(f"'{field.label}' must be a number.") from exc
            if parsed < 0:
                raise ValueError(f"'{field.label}' must be 0 or greater.")
            updated[field.key] = parsed
        self.save(updated)
        return updated

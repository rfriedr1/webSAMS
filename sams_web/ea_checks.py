"""EA checks: the daily check of each elemental analyzer with a check standard.

Once a day (or more often) the lab combusts a check standard — acetanilide
today — on each EA and compares the measured C % / N % with the standard's
pass window. It is a go/no-go *check* (ISO 17025 §6.4.10 intermediate
check), not a calibration. The values themselves live only in the EA
software; this module is their record.

Layout, mirroring the bench modules:

* settings (Setup → EA Checks): `CheckStandard`, `EaInstrument`,
  `EaCheckSettingsStore`;
* pure rules: `parse_percent`, `evaluate`, `summarize`, `missed_workdays`,
  `passing_streak` — no database, no request;
* `EaCheckLog`: the facade the routes use (entry strip, record, void, page);
* `EaCheckSignoffSubject`: plugs EA checks into the generic QC sign-off
  engine (`qc_signoff.py`).

Records are never updated or deleted — a wrong entry is voided — and each
row snapshots the standard's lot, reference values and pass window. See
ADR-0005.
"""

from __future__ import annotations

import math
import re
import statistics
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import cached_property
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Sequence

from sams_web.lab_staff import LabStaffStore
from sams_web.models import EaCheck
from sams_web.qc_signoff import QcSignoffs, SignoffItem, SignoffSubject
from sams_web.setup_sections import SETUP_SECTION_EA_CHECKS
from sams_web.setup_store import SetupStore

if TYPE_CHECKING:  # pragma: no cover
    from sams_web.services import SamsService


#: Elements an EA check can certify: (symbol, label). Each symbol has the
#: columns `conc_<s>`, `<s>_ref`, `<s>_min`, `<s>_max` on `ea_check_t`.
#: A standard certifying a new element (H, S) = one entry here plus one
#: additive `ALTER TABLE` — nothing else is restructured (ADR-0005).
ELEMENTS: tuple[tuple[str, str], ...] = (("c", "C"), ("n", "N"))

KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,19}$")
SUBJECT_TYPE = "ea_check"
COMMENT_MAX_LENGTH = 255
# Upper bound for the weighed-in standard: EA capsules hold a few mg, so a
# larger number is almost always a unit slip (µg typed as mg).
WEIGHT_MAX_MG = 100.0
DEFAULT_STEP = 0.1
DEFAULT_REMINDER_DAYS = 31

PERIODS: tuple[tuple[str, str], ...] = (
    ("unsigned", "Not yet signed off"),
    ("month", "This month"),
    ("3m", "Last 3 months"),
    ("12m", "Last 12 months"),
    ("all", "All"),
)

DEFAULT_SETTINGS: dict[str, Any] = {
    "standards": [
        {
            "key": "acetanilide",
            "name": "Acetanilide",
            "lot": "",
            "c": {"ref": 71.09, "min": 64.0, "max": 78.0, "step": 0.1},
            "n": {"ref": 10.36, "min": 9.4, "max": 11.4, "step": 0.1},
        }
    ],
    "instruments": [
        {"key": "ea1", "label": "EA 1 · AGE / MAG", "systems": ["age.1", "age.2", "mag"], "standards": ["acetanilide"]},
        {"key": "ea2", "label": "EA 2 · AGE64", "systems": ["age64.1", "age64.2"], "standards": ["acetanilide"]},
    ],
    "signoff_reminder_days": DEFAULT_REMINDER_DAYS,
}


# ---- Settings ----------------------------------------------------------------


@dataclass(frozen=True)
class ElementSpec:
    symbol: str
    label: str
    ref: float
    min: float
    max: float
    step: float = DEFAULT_STEP

    def in_window(self, value: float) -> bool:
        return self.min <= value <= self.max

    def gauge(self) -> dict[str, Any]:
        """Gauge range for the entry strip: the pass window plus 15 % of its
        width on each side, so a failing value can still be set by mouse."""
        pad = (self.max - self.min) * 0.15
        lo = max(_snap_down(self.min - pad, self.step), 0.0)
        hi = min(_snap_up(self.max + pad, self.step), 100.0)

        def pos(value: float) -> float:
            return round((value - lo) / (hi - lo) * 100, 3) if hi > lo else 50.0

        return {
            "symbol": self.symbol,
            "label": self.label,
            "ref": self.ref,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "lo": lo,
            "hi": hi,
            "decimals": max(0, -math.floor(math.log10(self.step) + 1e-9)) if self.step < 1 else 0,
            "pos_min": pos(self.min),
            "pos_max": pos(self.max),
            "pos_ref": pos(self.ref),
        }


@dataclass(frozen=True)
class CheckStandard:
    key: str
    name: str
    lot: str
    elements: tuple[ElementSpec, ...]

    def element(self, symbol: str) -> ElementSpec | None:
        return next((e for e in self.elements if e.symbol == symbol), None)


@dataclass(frozen=True)
class EaInstrument:
    key: str
    label: str
    systems: tuple[str, ...]
    standards: tuple[str, ...]  # first is the default

    @property
    def default_standard(self) -> str | None:
        return self.standards[0] if self.standards else None


@dataclass(frozen=True)
class EaCheckSettings:
    instruments: tuple[EaInstrument, ...]
    standards: tuple[CheckStandard, ...]
    reminder_days: int = DEFAULT_REMINDER_DAYS

    def standard(self, key: str | None) -> CheckStandard | None:
        return next((s for s in self.standards if s.key == key), None)

    def instrument(self, key: str | None) -> EaInstrument | None:
        return next((i for i in self.instruments if i.key == key), None)

    def standards_for(self, instrument: EaInstrument) -> list[CheckStandard]:
        return [s for key in instrument.standards if (s := self.standard(key)) is not None]


def _snap_down(value: float, step: float) -> float:
    return round(math.floor(value / step + 1e-9) * step, 6)


def _snap_up(value: float, step: float) -> float:
    return round(math.ceil(value / step - 1e-9) * step, 6)


def parse_number(raw: Any) -> float | None:
    """Blank → None; accepts a decimal comma (German keyboards)."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw).strip().replace(",", ".")
    if text == "":
        return None
    return float(text)  # ValueError for garbage — callers word the message


def _element_from_raw(symbol: str, label: str, raw: Any) -> ElementSpec | None:
    if not isinstance(raw, Mapping):
        return None
    try:
        ref, lo, hi = (parse_number(raw.get(k)) for k in ("ref", "min", "max"))
        step = parse_number(raw.get("step")) or DEFAULT_STEP
    except ValueError:
        return None
    if ref is None or lo is None or hi is None or not lo <= ref <= hi or step <= 0:
        return None
    return ElementSpec(symbol, label, ref, lo, hi, step)


def settings_from_raw(raw: Any) -> EaCheckSettings:
    """Build settings from the stored JSON, dropping anything malformed."""
    data = raw if isinstance(raw, Mapping) else DEFAULT_SETTINGS
    standards: list[CheckStandard] = []
    for item in data.get("standards") or []:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("key") or "").strip().lower()
        if not KEY_PATTERN.fullmatch(key) or any(s.key == key for s in standards):
            continue
        elements = tuple(
            spec
            for symbol, label in ELEMENTS
            if (spec := _element_from_raw(symbol, label, item.get(symbol))) is not None
        )
        if not elements:
            continue
        standards.append(
            CheckStandard(
                key=key,
                name=str(item.get("name") or key).strip() or key,
                lot=str(item.get("lot") or "").strip()[:40],
                elements=elements,
            )
        )
    known = {s.key for s in standards}
    instruments: list[EaInstrument] = []
    for item in data.get("instruments") or []:
        if not isinstance(item, Mapping):
            continue
        key = str(item.get("key") or "").strip().lower()
        if not KEY_PATTERN.fullmatch(key) or any(i.key == key for i in instruments):
            continue
        instruments.append(
            EaInstrument(
                key=key,
                label=str(item.get("label") or key).strip() or key,
                systems=tuple(str(s).strip() for s in item.get("systems") or [] if str(s).strip()),
                standards=tuple(s for s in (str(x).strip().lower() for x in item.get("standards") or []) if s in known),
            )
        )
    try:
        reminder = int(data.get("signoff_reminder_days") or DEFAULT_REMINDER_DAYS)
    except (TypeError, ValueError):
        reminder = DEFAULT_REMINDER_DAYS
    return EaCheckSettings(tuple(instruments), tuple(standards), max(reminder, 1))


def _split_list(raw: Any) -> list[str]:
    return [part.strip() for part in re.split(r"[,\s]+", str(raw or "")) if part.strip()]


class EaCheckSettingsStore:
    """Setup section `ea_checks` — see `DEFAULT_SETTINGS` for the shape."""

    section_key = SETUP_SECTION_EA_CHECKS

    def __init__(self, setup_store: SetupStore) -> None:
        self._store = setup_store

    def raw(self) -> dict[str, Any]:
        raw = self._store.get_section(self.section_key, default=None)
        return raw if isinstance(raw, dict) else DEFAULT_SETTINGS

    def load(self) -> EaCheckSettings:
        return settings_from_raw(self.raw())

    def update(self, payload: Mapping[str, Any], *, standards_in_use: Iterable[str] = ()) -> EaCheckSettings:
        """Validate the editor's parallel lists and save. `standards_in_use`
        are standard keys with logged checks; removing one is refused so
        the history stays resolvable."""
        standards: list[dict[str, Any]] = []
        keys = list(payload.get("std_key") or [])
        for index, raw_key in enumerate(keys):
            key = str(raw_key or "").strip().lower()

            def col(name: str) -> str:
                values = list(payload.get(name) or [])
                return str(values[index]).strip() if index < len(values) else ""

            if not key:
                continue
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError(
                    f"Standard key '{key}': use lowercase letters, numbers, dot, dash or underscore (max 20)."
                )
            if any(s["key"] == key for s in standards):
                raise ValueError(f"Standard key '{key}' is listed twice.")
            entry: dict[str, Any] = {"key": key, "name": col("std_name") or key, "lot": col("std_lot")[:40]}
            for symbol, label in ELEMENTS:
                texts = {k: col(f"std_{symbol}_{k}") for k in ("ref", "min", "max", "step")}
                if not any(texts[k] for k in ("ref", "min", "max")):
                    continue  # element not certified by this standard
                try:
                    ref, lo, hi = (parse_number(texts[k]) for k in ("ref", "min", "max"))
                    step = parse_number(texts["step"]) or DEFAULT_STEP
                except ValueError:
                    raise ValueError(f"{entry['name']}: {label} values must be numbers.") from None
                if ref is None or lo is None or hi is None:
                    raise ValueError(f"{entry['name']}: give {label} reference, min and max (or leave all three blank).")
                if not 0 < lo <= ref <= hi <= 100:
                    raise ValueError(f"{entry['name']}: {label} needs 0 < min ≤ reference ≤ max ≤ 100.")
                if not 0 < step <= hi - lo:
                    raise ValueError(f"{entry['name']}: {label} gauge step must be above 0 and below the window width.")
                entry[symbol] = {"ref": ref, "min": lo, "max": hi, "step": step}
            if not any(symbol in entry for symbol, _ in ELEMENTS):
                raise ValueError(f"{entry['name']}: certify at least one element (reference, min and max).")
            standards.append(entry)

        removed = {s.key for s in self.load().standards} - {s["key"] for s in standards}
        blocked = sorted(removed & set(standards_in_use))
        if blocked:
            raise ValueError(
                f"Standard '{blocked[0]}' has logged checks and cannot be removed — the history refers to it."
            )
        known = {s["key"] for s in standards}

        instruments: list[dict[str, Any]] = []
        inst_keys = list(payload.get("inst_key") or [])
        for index, raw_key in enumerate(inst_keys):
            key = str(raw_key or "").strip().lower()

            def icol(name: str) -> str:
                values = list(payload.get(name) or [])
                return str(values[index]).strip() if index < len(values) else ""

            if not key:
                continue
            if not KEY_PATTERN.fullmatch(key):
                raise ValueError(f"EA key '{key}': use lowercase letters, numbers, dot, dash or underscore (max 20).")
            if any(i["key"] == key for i in instruments):
                raise ValueError(f"EA key '{key}' is listed twice.")
            std_keys = [s.lower() for s in _split_list(icol("inst_standards"))]
            unknown = [s for s in std_keys if s not in known]
            if unknown:
                raise ValueError(f"EA '{key}': unknown standard '{unknown[0]}'.")
            if not std_keys:
                raise ValueError(f"EA '{key}': list at least one check standard.")
            instruments.append(
                {
                    "key": key,
                    "label": icol("inst_label") or key,
                    "systems": _split_list(icol("inst_systems")),
                    "standards": std_keys,
                }
            )
        try:
            reminder = int(str(payload.get("signoff_reminder_days") or DEFAULT_REMINDER_DAYS).strip())
        except ValueError:
            raise ValueError("Sign-off reminder must be a whole number of days.") from None
        if not 1 <= reminder <= 366:
            raise ValueError("Sign-off reminder must be between 1 and 366 days.")
        cleaned = {"standards": standards, "instruments": instruments, "signoff_reminder_days": reminder}
        self._store.set_section(self.section_key, cleaned)
        return settings_from_raw(cleaned)


# ---- Pure rules ----------------------------------------------------------------


def parse_percent(raw: Any) -> float | None:
    """A measured mass fraction: blank → None, `71,84` or `71.84` → 71.84.
    Raises `ValueError` for anything that is not a number in (0, 100]."""
    value = parse_number(raw)
    if value is None:
        return None
    if not 0 < value <= 100:
        raise ValueError("must be between 0 and 100 %")
    return round(value, 3)


def parse_weight(raw: Any) -> float | None:
    """Weight of the standard in mg: blank → None (optional), `1,502` or
    `1.502` → 1.502. Raises `ValueError` outside (0, WEIGHT_MAX_MG]."""
    try:
        value = parse_number(raw)
    except ValueError:
        raise ValueError("is not a number") from None
    if value is None:
        return None
    if not 0 < value <= WEIGHT_MAX_MG:
        raise ValueError(f"must be between 0 and {WEIGHT_MAX_MG:g} mg")
    return round(value, 3)


def fmt_weight(value: Any) -> str:
    return "" if value is None else f"{float(value):.3f} mg"


def check_value(check: Any, symbol: str) -> float | None:
    value = getattr(check, f"conc_{symbol}", None)
    return float(value) if value is not None else None


def evaluate(values: Mapping[str, float], standard: CheckStandard) -> tuple[bool, dict[str, bool]]:
    """Pass/fail per certified element (limits inclusive) and overall."""
    per_element = {e.symbol: e.in_window(values[e.symbol]) for e in standard.elements}
    return all(per_element.values()), per_element


def is_workday(day: date) -> bool:
    return day.weekday() < 5


def missed_workdays(checked_days: Iterable[date], start: date, end: date) -> list[date]:
    """Mon–Fri days in [start, end] without any check. Public holidays are
    not known to the app, so they count as missed."""
    have = set(checked_days)
    missed: list[date] = []
    day = start
    while day <= end:
        if is_workday(day) and day not in have:
            missed.append(day)
        day += timedelta(days=1)
    return missed


def day_outcomes(checks: Iterable[Any]) -> dict[date, bool]:
    """Per day, whether its *latest* non-voided attempt passed."""
    latest: dict[date, Any] = {}
    for check in checks:
        if check.voided:
            continue
        day = check.checked_at.date()
        if day not in latest or (check.checked_at, check.id) >= (latest[day].checked_at, latest[day].id):
            latest[day] = check
    return {day: bool(check.passed) for day, check in latest.items()}


def passing_streak(outcomes: Mapping[date, bool], today: date) -> int:
    """Consecutive workdays, back from today, whose latest attempt passed.
    Today counts only once it has a check; weekends never break a streak."""
    streak = 0
    day = today if today in outcomes else today - timedelta(days=1)
    for _ in range(3660):
        if day in outcomes:
            if not outcomes[day]:
                break
            streak += 1
        elif is_workday(day):
            break
        day -= timedelta(days=1)
    return streak


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def summarize(checks: Sequence[Any], standard: CheckStandard | None, *, today: date | None = None) -> dict[str, Any]:
    """The statistics an ISO 17025 review needs, kept to the minimum:
    n, n failed, and per certified element mean, s, bias against the
    reference, the ±2s/±3s lines and how many points lie outside ±3s;
    plus the workdays without a check. Voided checks are ignored.

    Mean, s and bias describe the instrument in normal operation, so they
    use the *passed* checks only; failed checks (a known nonconformity,
    commented and re-run) are counted in `n_failed` and listed separately
    — one leaking run would otherwise multiply s several times.

    The reference value and window come from the newest check's snapshot,
    so the numbers match what was in force when the checks were made.
    JSON-serialisable: it is stored as `qc_signoff_t.stats_json`.
    """
    valid = [c for c in checks if not c.voided]
    result: dict[str, Any] = {
        "n": len(valid),
        "n_failed": sum(1 for c in valid if not c.passed),
        "from": valid[0].checked_at.isoformat(sep=" ") if valid else None,
        "to": valid[-1].checked_at.isoformat(sep=" ") if valid else None,
        "elements": [],
        "missed_workdays": 0,
    }
    if valid:
        end = min(valid[-1].checked_at.date(), today) if today else valid[-1].checked_at.date()
        result["missed_workdays"] = len(
            missed_workdays((c.checked_at.date() for c in valid), valid[0].checked_at.date(), end)
        )
    for symbol, label in ELEMENTS:
        spec = standard.element(symbol) if standard else None
        values = [v for c in valid if c.passed and (v := check_value(c, symbol)) is not None]
        last = next((c for c in reversed(valid) if getattr(c, f"{symbol}_ref", None) is not None), None)
        ref = float(getattr(last, f"{symbol}_ref")) if last else (spec.ref if spec else None)
        lo = float(getattr(last, f"{symbol}_min")) if last else (spec.min if spec else None)
        hi = float(getattr(last, f"{symbol}_max")) if last else (spec.max if spec else None)
        if ref is None and not values:
            continue
        mean = statistics.fmean(values) if values else None
        sd = statistics.stdev(values) if len(values) >= 2 else None
        bias = mean - ref if mean is not None and ref is not None else None
        outside_3s = (
            sum(1 for v in values if abs(v - mean) > 3 * sd) if mean is not None and sd else 0
        )
        result["elements"].append(
            {
                "symbol": symbol,
                "label": label,
                "ref": ref,
                "min": lo,
                "max": hi,
                "n": len(values),
                "mean": _round(mean),
                "sd": _round(sd),
                "bias": _round(bias),
                "bias_pct": _round(bias / ref * 100, 2) if bias is not None and ref else None,
                "lo2": _round(mean - 2 * sd) if sd else None,
                "hi2": _round(mean + 2 * sd) if sd else None,
                "lo3": _round(mean - 3 * sd) if sd else None,
                "hi3": _round(mean + 3 * sd) if sd else None,
                "n_outside_3s": outside_3s,
            }
        )
    return result


# ---- Display helpers ---------------------------------------------------------


def fmt_value(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def values_text(check: Any) -> str:
    parts = [
        f"{label} {fmt_value(check_value(check, symbol))} %"
        for symbol, label in ELEMENTS
        if check_value(check, symbol) is not None
    ]
    return " · ".join(parts)


def check_row(check: EaCheck, *, signoff_id: int | None = None, labels: Mapping[str, str] | None = None) -> dict[str, Any]:
    """A check as plain data for templates, the chart and the JSON API."""
    return {
        "id": check.id,
        "ea": check.ea,
        "ea_label": (labels or {}).get(check.ea, check.ea),
        "standard": check.standard,
        "rm_lot": check.rm_lot or "",
        "checked_at": check.checked_at.isoformat(sep=" ", timespec="minutes"),
        "date": check.checked_at.strftime("%Y-%m-%d"),
        "time": check.checked_at.strftime("%H:%M"),
        "weight_mg": float(check.weight_mg) if check.weight_mg is not None else None,
        "weight_text": fmt_weight(check.weight_mg),
        **{f"conc_{s}": check_value(check, s) for s, _ in ELEMENTS},
        "values_text": values_text(check),
        "passed": bool(check.passed),
        "operator": check.operator,
        "comment": check.comment or "",
        "voided": bool(check.voided),
        "void_reason": check.void_reason or "",
        "voided_by": check.voided_by or "",
        "signoff_id": signoff_id,
    }


# ---- Facade --------------------------------------------------------------------


@dataclass
class RecordOutcome:
    success: bool
    message: str = ""
    error: str | None = None
    check: EaCheck | None = None


def _sparks(standard: CheckStandard | None, history: Sequence[Any]) -> list[dict[str, Any]]:
    """One trend line per certified element of ``standard`` (C % and N % for
    acetanilide); an element with fewer than two values has no line."""
    sparks = []
    for el in standard.elements if standard else ():
        points = [
            {
                "v": check_value(c, el.symbol),
                "passed": bool(c.passed),
                "checked_at": c.checked_at.isoformat(sep=" ", timespec="minutes"),
                "operator": c.operator,
            }
            for c in history
            if check_value(c, el.symbol) is not None
        ]
        if len(points) > 1:
            sparks.append({"symbol": el.symbol, "element": el.gauge(), "points": points})
    return sparks


class EaCheckLog:
    """What the routes use. One instance per request."""

    def __init__(self, service: "SamsService", *, now: datetime | None = None) -> None:
        self.service = service
        self.repo = service.repo
        self.settings = EaCheckSettingsStore(service.setup_store).load()
        self.staff = LabStaffStore(service.setup_store)
        self._now = now

    def now(self) -> datetime:
        return self._now or datetime.now().replace(microsecond=0)

    @cached_property
    def missing_tables(self) -> list[str]:
        return self.repo.missing_qc_tables()

    @property
    def available(self) -> bool:
        return not self.missing_tables

    def _labels(self) -> dict[str, str]:
        return {i.key: i.label for i in self.settings.instruments}

    # -- entry strip --

    def strip_view(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "available": self.available,
            "missing_tables": self.missing_tables,
            "staff": self.staff.names(),
            "cards": [],
            "configured": bool(self.settings.instruments),
        }
        if not self.available:
            return base
        now = self.now()
        start_of_day = datetime.combine(now.date(), time.min)
        today_checks = self.repo.list_ea_checks(since=start_of_day)
        unsigned_since = self.repo.oldest_unsigned_ea_check_at(SUBJECT_TYPE)
        for instrument in self.settings.instruments:
            base["cards"].append(
                self._card(instrument, [c for c in today_checks if c.ea == instrument.key], unsigned_since, now)
            )
        return base

    def _card(
        self,
        instrument: EaInstrument,
        today_checks: list[EaCheck],
        unsigned_since: Mapping[str, datetime],
        now: datetime,
    ) -> dict[str, Any]:
        valid = [c for c in today_checks if not c.voided]
        latest = valid[-1] if valid else None
        if latest is None:
            state, state_label = "pending", "not checked yet"
        elif latest.passed:
            state, state_label = "passed", f"passed {latest.checked_at:%H:%M} · {latest.operator}"
        else:
            state, state_label = "failed", f"failed {latest.checked_at:%H:%M} — re-run"
        standards = self.settings.standards_for(instrument)
        default = self.settings.standard(instrument.default_standard)
        history = (
            self.repo.latest_ea_checks(ea=instrument.key, standard=default.key, limit=30) if default else []
        )
        streak_source = self.repo.list_ea_checks(
            ea=instrument.key, since=now - timedelta(days=120), include_voided=False
        )
        oldest_unsigned = unsigned_since.get(instrument.key)
        return {
            "key": instrument.key,
            "label": instrument.label,
            "systems": list(instrument.systems),
            "state": state,
            "state_label": state_label,
            "latest": check_row(latest) if latest else None,
            "attempts": [check_row(c) for c in valid],
            "streak": passing_streak(day_outcomes(streak_source), now.date()),
            "oldest_unsigned": oldest_unsigned,
            "overdue": bool(
                oldest_unsigned and now - oldest_unsigned > timedelta(days=self.settings.reminder_days)
            ),
            "config": {
                "ea": instrument.key,
                "default_standard": default.key if default else None,
                "standards": [
                    {
                        "key": s.key,
                        "name": s.name,
                        "lot": s.lot,
                        "elements": [e.gauge() for e in s.elements],
                    }
                    for s in standards
                ],
                "sparks": _sparks(default, history),
            },
        }

    def system_warnings(self, strip: Mapping[str, Any]) -> dict[str, str]:
        """Graph systems whose EA has no passing latest attempt today."""
        warnings: dict[str, str] = {}
        for card in strip.get("cards") or []:
            if card["state"] == "passed":
                continue
            for system in card["systems"]:
                warnings[system] = f"{card['label']}: {card['state_label']}"
        return warnings

    def dashboard_tile(self) -> dict[str, Any] | None:
        if not self.settings.instruments:
            return None
        strip = self.strip_view()
        if not strip["available"]:
            return {"available": False, "items": []}
        return {
            "available": True,
            "items": [
                {
                    "label": c["label"],
                    "state": c["state"],
                    "state_label": c["state_label"],
                    "overdue": c["overdue"],
                }
                for c in strip["cards"]
            ],
            "overdue": any(c["overdue"] for c in strip["cards"]),
        }

    # -- writes --

    def record(self, form: Mapping[str, Any]) -> RecordOutcome:
        if not self.available:
            return RecordOutcome(False, error="The EA check tables do not exist yet — see Setup notes.")
        instrument = self.settings.instrument(str(form.get("ea") or "").strip())
        if instrument is None:
            return RecordOutcome(False, error="Unknown EA — check Setup → EA Checks.")
        standard_key = str(form.get("standard") or instrument.default_standard or "").strip()
        standard = self.settings.standard(standard_key)
        if standard is None or standard.key not in instrument.standards:
            return RecordOutcome(False, error=f"{instrument.label}: unknown check standard '{standard_key}'.")
        operator = str(form.get("operator") or "").strip()
        names = self.staff.names()
        if not operator:
            return RecordOutcome(False, error="Pick who measured the check.")
        if names and operator not in names:
            return RecordOutcome(False, error=f"'{operator}' is not in Setup → Lab Staff.")
        values: dict[str, float] = {}
        for spec in standard.elements:
            try:
                value = parse_percent(form.get(f"value_{spec.symbol}"))
            except ValueError as exc:
                return RecordOutcome(False, error=f"{spec.label} %: {exc}.")
            if value is None:
                missing = " and ".join(f"{e.label} %" for e in standard.elements)
                return RecordOutcome(False, error=f"Set {missing} first.")
            values[spec.symbol] = value
        try:
            weight = parse_weight(form.get("weight_mg"))
        except ValueError as exc:
            return RecordOutcome(False, error=f"Weight {exc}.")
        passed, _ = evaluate(values, standard)
        comment = str(form.get("comment") or "").strip()
        if len(comment) > COMMENT_MAX_LENGTH:
            return RecordOutcome(False, error=f"Comment is longer than {COMMENT_MAX_LENGTH} characters.")
        if not passed and not comment:
            return RecordOutcome(
                False, error="Out of the pass window — add a short comment (what you will do) before logging."
            )
        payload: dict[str, Any] = {
            "ea": instrument.key,
            "standard": standard.key,
            "rm_lot": standard.lot or None,
            "checked_at": self.now(),
            "weight_mg": weight,
            "passed": 1 if passed else 0,
            "operator": operator,
            "comment": comment or None,
            "voided": 0,
        }
        for symbol, _ in ELEMENTS:
            spec = standard.element(symbol)
            payload[f"conc_{symbol}"] = values.get(symbol)
            payload[f"{symbol}_ref"] = spec.ref if spec else None
            payload[f"{symbol}_min"] = spec.min if spec else None
            payload[f"{symbol}_max"] = spec.max if spec else None
        check = self.repo.add_ea_check(payload)
        self.service.session.commit()
        verdict = "passed" if passed else "FAILED"
        return RecordOutcome(True, message=f"{instrument.label} {verdict}: {values_text(check)}", check=check)

    def void(self, check_id: int, *, reason: str, by: str) -> RecordOutcome:
        if not self.available:
            return RecordOutcome(False, error="The EA check tables do not exist yet.")
        check = self.repo.get_ea_check(check_id)
        if check is None:
            return RecordOutcome(False, error=f"EA check {check_id} not found.")
        if check.voided:
            return RecordOutcome(False, error="This check is already voided.")
        if self.repo.signed_item_refs(SUBJECT_TYPE, [str(check.id)]):
            return RecordOutcome(False, error="This check is signed off and can no longer be voided.")
        reason = reason.strip()
        by = by.strip()
        if not reason:
            return RecordOutcome(False, error="Give a reason for voiding the check.")
        if len(reason) > COMMENT_MAX_LENGTH:
            return RecordOutcome(False, error=f"Reason is longer than {COMMENT_MAX_LENGTH} characters.")
        names = self.staff.names()
        if not by or (names and by not in names):
            return RecordOutcome(False, error="Pick who is voiding the check (Setup → Lab Staff).")
        self.repo.void_ea_check(check, reason=reason, by=by, at=self.now())
        self.service.session.commit()
        return RecordOutcome(True, message=f"Check of {check.checked_at:%d.%m.%Y %H:%M} voided.", check=check)

    # -- page --

    def _period_start(self, period: str, oldest_unsigned: datetime | None) -> datetime | None:
        today = self.now().date()
        if period == "month":
            return datetime.combine(today.replace(day=1), time.min)
        if period == "3m":
            return datetime.combine(today - timedelta(days=91), time.min)
        if period == "12m":
            return datetime.combine(today - timedelta(days=365), time.min)
        if period == "all":
            return None
        # "unsigned": from the day of the oldest unsigned check
        return datetime.combine((oldest_unsigned or self.now()).date(), time.min)

    def page_view(self, *, ea: str | None = None, period: str = "unsigned") -> dict[str, Any]:
        period = period if period in dict(PERIODS) else "unsigned"
        strip = self.strip_view()
        context: dict[str, Any] = {
            "ea_strip": strip,
            "periods": PERIODS,
            "period": period,
            "period_label": dict(PERIODS)[period],
            "ea_filter": ea or "",
            "instruments": self.settings.instruments,
            "sections": [],
            "history_rows": [],
            "signoff_rows": [],
            "signers": self.staff.signers(),
            "staff": self.staff.names(),
            "reminder_days": self.settings.reminder_days,
        }
        if not strip["available"]:
            return context
        labels = self._labels()
        instruments = [i for i in self.settings.instruments if not ea or i.key == ea]
        signoffs = QcSignoffs(self.service, now=self.now())
        oldest = self.repo.oldest_unsigned_ea_check_at(SUBJECT_TYPE)
        relevant_oldest = [oldest[i.key] for i in instruments if i.key in oldest]
        since = self._period_start(period, min(relevant_oldest) if relevant_oldest else None)
        period_checks = [c for c in self.repo.list_ea_checks(since=since) if c.ea in {i.key for i in instruments}]
        signed = self.repo.signed_item_refs(SUBJECT_TYPE, [str(c.id) for c in period_checks])
        subject = EaCheckSignoffSubject()
        for instrument in instruments:
            in_use = {c.standard for c in period_checks if c.ea == instrument.key}
            for standard_key in list(instrument.standards) + sorted(in_use - set(instrument.standards)):
                standard = self.settings.standard(standard_key)
                key = subject_key(instrument.key, standard_key)
                checks = [c for c in period_checks if c.ea == instrument.key and c.standard == standard_key]
                unsigned_items = signoffs.unsigned(subject, key)
                if period == "unsigned":
                    stats_checks = [c for c in checks if str(c.id) not in signed]
                else:
                    stats_checks = checks
                if not checks and not unsigned_items and standard_key != instrument.default_standard:
                    continue
                review_checks = [item.record for item in unsigned_items]
                stats = summarize(stats_checks, standard, today=self.now().date())
                review = summarize(review_checks, standard, today=self.now().date())
                oldest_at = review_checks[0].checked_at if review_checks else None
                context["sections"].append(
                    {
                        "key": key,
                        "dom_id": f"ea-{instrument.key}-{standard_key}".replace(".", "-"),
                        "ea": instrument.key,
                        "ea_label": instrument.label,
                        "standard": standard_key,
                        "standard_label": standard.name if standard else standard_key,
                        "lot": standard.lot if standard else "",
                        "stats": stats,
                        "review": review,
                        "review_rows": [check_row(c) for c in review_checks],
                        "review_period_to": review_checks[-1].checked_at.isoformat() if review_checks else "",
                        "unsigned_count": len(review_checks),
                        "review_range": (
                            f"{review_checks[0].checked_at:%d.%m.%y} – {review_checks[-1].checked_at:%d.%m.%y}"
                            if review_checks
                            else ""
                        ),
                        "oldest_unsigned": oldest_at,
                        "overdue": bool(
                            oldest_at and self.now() - oldest_at > timedelta(days=self.settings.reminder_days)
                        ),
                        "chart": {
                            "elements": [e.gauge() for e in standard.elements] if standard else [],
                            "stats": stats["elements"],
                            "points": [check_row(c) for c in stats_checks if not c.voided],
                        },
                        "review_chart": {
                            "elements": [e.gauge() for e in standard.elements] if standard else [],
                            "stats": review["elements"],
                            "points": [check_row(c) for c in review_checks],
                        },
                    }
                )
        context["history_rows"] = [
            check_row(c, signoff_id=signed.get(str(c.id)), labels=labels) for c in reversed(period_checks)
        ]
        context["signoff_rows"] = signoffs.history(subject_type=SUBJECT_TYPE)
        return context

    def api_rows(self, *, ea: str | None = None, standard: str | None = None, since: datetime | None = None) -> list[dict[str, Any]]:
        checks = self.repo.list_ea_checks(ea=ea or None, standard=standard or None, since=since)
        signed = self.repo.signed_item_refs(SUBJECT_TYPE, [str(c.id) for c in checks])
        labels = self._labels()
        return [check_row(c, signoff_id=signed.get(str(c.id)), labels=labels) for c in checks]


# ---- Sign-off subject ------------------------------------------------------------


def subject_key(ea: str, standard: str) -> str:
    return f"{ea}|{standard}"


def split_subject_key(key: str) -> tuple[str, str]:
    ea, _, standard = key.partition("|")
    return ea, standard


class EaCheckSignoffSubject(SignoffSubject):
    """EA checks of one (EA, standard) pair, for the QC sign-off engine."""

    subject_type = SUBJECT_TYPE
    item_type = SUBJECT_TYPE
    label = "EA check"
    body_template = "qc/_ea_check_signoff_body.html"
    return_url = "/lab/ea-checks"

    def describe(self, service: "SamsService", key: str) -> str:
        settings = EaCheckSettingsStore(service.setup_store).load()
        ea, standard = split_subject_key(key)
        instrument = settings.instrument(ea)
        std = settings.standard(standard)
        return f"{instrument.label if instrument else ea} — {std.name if std else standard}"

    def items(self, service: "SamsService", key: str, until: datetime | None = None) -> list[SignoffItem]:
        ea, standard = split_subject_key(key)
        checks = service.repo.list_ea_checks(ea=ea, standard=standard, until=until, include_voided=False)
        return [SignoffItem(ref=str(c.id), at=c.checked_at, flagged=not c.passed, record=c) for c in checks]

    def summarize(self, service: "SamsService", key: str, items: Sequence[SignoffItem]) -> dict[str, Any]:
        _, standard = split_subject_key(key)
        settings = EaCheckSettingsStore(service.setup_store).load()
        return summarize([i.record for i in items], settings.standard(standard))

    def body_context(
        self, service: "SamsService", key: str, item_refs: Sequence[str], stats: Mapping[str, Any]
    ) -> dict[str, Any]:
        ids = {int(ref) for ref in item_refs if ref.isdigit()}
        ea, standard = split_subject_key(key)
        checks = [c for c in service.repo.list_ea_checks(ea=ea, standard=standard) if c.id in ids]
        settings = EaCheckSettingsStore(service.setup_store).load()
        std = settings.standard(standard)
        return {
            "rows": [check_row(c) for c in checks],
            "chart": {
                "elements": [e.gauge() for e in std.elements] if std else [],
                "stats": list(stats.get("elements") or []),
                "points": [check_row(c) for c in checks],
            },
        }

"""Transfer measured results from targets to their samples (ADR-0002).

BATS evaluates each **target** (`target_t`: FM, δ¹³C, C14 age, calibrated
ranges — ADR-0003, read only here). The result reported for a **sample**
lives on `sample_t` (`c14_age`, `c14_age_sig`, `av_fm`, `av_fm_sig`,
`av_dc13`, `cal1sMin` …) and is chosen by the operator from the sample's
targets. Lab → Analysis → Magazine → *Actions* → *Transfer…* does that for
every sample measured in the open magazine, like the legacy SAMS's
*Transfer* tab.

Per sample the operator ticks targets (`choices`: sample_nr → target refs
`"prep.target"`), from **all** its targets, not only this magazine's:

- **one** ticked target → its values are copied as they are, calibrated
  ranges included (the legacy `TransferAgeFromTarget`);
- **several** → an inverse-variance **weighted FM mean** (the lab's choice
  for ADR-0002, 2026-11): FM = Σ(f/σ²)/Σ(1/σ²), σ = 1/√Σ(1/σ²), age =
  −8033·ln FM, age σ = 8033·σ/FM, δ¹³C the plain mean. The calibrated ranges
  are **cleared**: they belong to one target and webSAMS does not calibrate
  (ADR-0003). The ticked targets' agreement is tested (Ward & Wilson 1978,
  T against χ² at 95 %) and shown, never enforced;
- **none** → the sample is left alone.

Defaults: a sample with exactly one measured target has it ticked; a sample
with several has **nothing** ticked — the operator decides (lab's choice).

**Limit ages** (legacy rule, kept): when FM < 2σ (σ at least 0.0005) the
sample gets the lower limit −8033·ln(FM + 2σ), rounded to 100 years, with
age sigma 99999 — the convention of the samples stored so far.

Standards are skipped — sample # below 10000 or a standard type (oxa2,
blank, IAEA C1–C8: `WAITING_FOR_MEAS_STANDARD_TYPES`): IAEA C6 alone has
500+ targets and none of them carries a reported result. Always preview, then transfer; the
transfer reads everything again and writes only new and differing results.
"""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

from sams_web.repositories import WAITING_FOR_MEAS_STANDARD_TYPES

if TYPE_CHECKING:
    from sams_web.services import SamsService


AGE_FACTOR = 8033.0  # Libby mean life: age = −8033·ln(F14C)
MIN_FM_SIGMA = 0.0005  # legacy floor for the limit-age test
LIMIT_AGE_SIGMA = 99999.0  # legacy marker of a lower-limit age
FIRST_CUSTOMER_SAMPLE_NR = 10000  # below: standards (as the Waiting for measurement queue)
STANDARD_TYPES = frozenset(WAITING_FOR_MEAS_STANDARD_TYPES)
NOTHING_CHANGED = "Nothing was changed."

#: sample_t columns written, in display order (names as in `models.Sample`).
RESULT_FIELDS = (
    "c14_age", "c14_age_sig", "av_fm", "av_fm_sig", "av_dc13", "cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max",
)
CAL_FIELDS = ("cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max")
#: How close a stored value must be to count as the same.
_TOLERANCE = {
    "c14_age": 0.5, "c14_age_sig": 0.5, "av_fm": 5e-6, "av_fm_sig": 5e-6, "av_dc13": 5e-5,
    "cal1s_min": 0.5, "cal1s_max": 0.5, "cal2s_min": 0.5, "cal2s_max": 0.5,
}
#: χ² at 95 % for 1…20 degrees of freedom (Ward & Wilson's test of a mean).
_CHI2_95 = (
    3.841, 5.991, 7.815, 9.488, 11.070, 12.592, 14.067, 15.507, 16.919, 18.307,
    19.675, 21.026, 22.362, 23.685, 24.996, 26.296, 27.587, 28.869, 30.144, 31.410,
)

STATUS_NEW = "new"
STATUS_REPLACES = "replaces"
STATUS_SAME = "same"
STATUS_CHOOSE = "choose"
STATUS_SKIP = "skip"
STATUS_NOT_MEASURED = "not_measured"
STATUS_INVALID = "invalid"
STATUS_ORDER = (
    STATUS_NEW, STATUS_REPLACES, STATUS_SAME, STATUS_CHOOSE, STATUS_SKIP, STATUS_NOT_MEASURED, STATUS_INVALID,
)
WRITES = (STATUS_NEW, STATUS_REPLACES)


# ---- Math ---------------------------------------------------------------------

def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def limit_age(fm: float | None, fm_sig: float | None) -> float | None:
    """The legacy lower-limit age for a result near background, else None."""
    if fm is None or fm_sig is None:
        return None
    sigma = max(fm_sig, MIN_FM_SIGMA)
    if fm >= 2 * sigma:
        return None
    return round(-math.log(fm + 2 * sigma) * AGE_FACTOR / 100) * 100


def single_result(target: dict[str, Any]) -> dict[str, Any]:
    """One target's values for its sample, as the legacy transfer did."""
    fm, fm_sig = _num(target.get("fm")), _num(target.get("fm_sig"))
    result: dict[str, Any] = {
        "c14_age": _num(target.get("c14_age")),
        "c14_age_sig": _num(target.get("c14_age_sig")),
        "av_fm": fm,
        "av_fm_sig": fm_sig,
        "av_dc13": _num(target.get("dc13")),
        **{field: _num(target.get(field)) for field in CAL_FIELDS},
    }
    limit = limit_age(fm, fm_sig)
    if limit is not None:
        result["c14_age"], result["c14_age_sig"] = float(limit), LIMIT_AGE_SIGMA
    return {"values": result, "limit": limit is not None, "agreement": None}


def _chi2_95(df: int) -> float:
    if df <= len(_CHI2_95):
        return _CHI2_95[df - 1]
    # Wilson–Hilferty approximation beyond the table.
    z = 1.6449
    return df * (1 - 2 / (9 * df) + z * math.sqrt(2 / (9 * df))) ** 3


def mean_result(targets: list[dict[str, Any]]) -> dict[str, Any]:
    """Weighted FM mean of several targets (ADR-0002). Raises ValueError
    naming the target when one cannot be averaged."""
    weights: list[tuple[float, float]] = []
    for target in targets:
        fm, fm_sig = _num(target.get("fm")), _num(target.get("fm_sig"))
        if fm is None or fm_sig is None or fm_sig <= 0:
            raise ValueError(f"Target {target_ref(target)} has no FM with a sigma, so it cannot be averaged.")
        weights.append((fm, fm_sig))
    total = sum(1 / s**2 for _, s in weights)
    fm_mean = sum(f / s**2 for f, s in weights) / total
    fm_sigma = 1 / math.sqrt(total)
    t_stat = sum((f - fm_mean) ** 2 / s**2 for f, s in weights)
    critical = _chi2_95(len(weights) - 1)
    dc13 = [value for value in (_num(t.get("dc13")) for t in targets) if value is not None]
    limit = limit_age(fm_mean, fm_sigma)
    if limit is not None:
        age, age_sig = float(limit), LIMIT_AGE_SIGMA
    else:
        age, age_sig = -AGE_FACTOR * math.log(fm_mean), AGE_FACTOR * fm_sigma / fm_mean
    values = {
        "c14_age": age,
        "c14_age_sig": age_sig,
        "av_fm": fm_mean,
        "av_fm_sig": fm_sigma,
        "av_dc13": sum(dc13) / len(dc13) if dc13 else None,
        **{field: None for field in CAL_FIELDS},
    }
    agreement = {"t": round(t_stat, 2), "critical": round(critical, 2), "ok": t_stat <= critical}
    return {"values": values, "limit": limit is not None, "agreement": agreement}


def _same(stored: dict[str, Any], values: dict[str, Any]) -> bool:
    for field in RESULT_FIELDS:
        old, new = _num(stored.get(field)), values.get(field)
        if old is None and new is None:
            continue
        if old is None or new is None or abs(old - new) > _TOLERANCE[field]:
            return False
    return True


# ---- Choices --------------------------------------------------------------------

def target_ref(target: dict[str, Any]) -> str:
    return f"{int(target['prep_nr'])}.{int(target['target_nr'])}"


def is_measured(target: dict[str, Any]) -> bool:
    return _num(target.get("c14_age")) is not None


def parse_choices(text: str | None) -> dict[int, list[str]]:
    """`{"48211": ["1.1", "2.1"], …}` from the dialog. Raises ValueError on
    anything else (the form is ours; a malformed one is refused whole)."""
    if not text:
        return {}
    try:
        raw = json.loads(text)
    except ValueError:
        raise ValueError("The ticked targets could not be read. Reload the page and try again.") from None
    if not isinstance(raw, dict):
        raise ValueError("The ticked targets could not be read. Reload the page and try again.")
    choices: dict[int, list[str]] = {}
    for key, refs in raw.items():
        try:
            sample_nr = int(key)
        except (TypeError, ValueError):
            raise ValueError(f"{key!r} is not a sample number.") from None
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError(f"The ticked targets of sample {sample_nr} could not be read.")
        choices[sample_nr] = list(dict.fromkeys(ref.strip() for ref in refs))
    return choices


def is_standard(sample: dict[str, Any]) -> bool:
    return int(sample["sample_nr"]) < FIRST_CUSTOMER_SAMPLE_NR or sample.get("type") in STANDARD_TYPES


def default_refs(targets: list[dict[str, Any]]) -> list[str]:
    measured = [target_ref(t) for t in targets if is_measured(t)]
    return measured if len(measured) == 1 else []


# ---- Preview and transfer ---------------------------------------------------------

def _target_row(target: dict[str, Any], magazine: str, chosen: set[str]) -> dict[str, Any]:
    ref = target_ref(target)
    return {
        "ref": ref,
        "target_id": f"{int(target['sample_nr'])}.{ref}",
        "magazine": target.get("magazine"),
        "position": target.get("position"),
        "in_magazine": target.get("magazine") == magazine,
        "discarded": bool(_num(target.get("stop"))),
        "frozen": _num(target.get("editallowed")) == 2,
        "measured": is_measured(target),
        "chosen": ref in chosen,
        "fm": _num(target.get("fm")),
        "fm_sig": _num(target.get("fm_sig")),
        "c14_age": _num(target.get("c14_age")),
        "c14_age_sig": _num(target.get("c14_age_sig")),
        "dc13": _num(target.get("dc13")),
    }


def _position_key(sample: dict[str, Any], magazine: str) -> tuple[float, int]:
    positions = []
    for target in sample["targets"]:
        if target.get("magazine") == magazine:
            try:
                positions.append(float(str(target.get("position")).strip()))
            except (TypeError, ValueError):
                pass
    return (min(positions) if positions else math.inf, int(sample["sample_nr"]))


def _sample_row(sample: dict[str, Any], magazine: str, refs: list[str] | None) -> dict[str, Any]:
    targets = sample["targets"]
    by_ref = {target_ref(t): t for t in targets}
    measured = [t for t in targets if is_measured(t)]
    chosen_refs = default_refs(targets) if refs is None else refs
    stored = {field: _num(sample.get(field)) for field in RESULT_FIELDS}
    row: dict[str, Any] = {
        "sample_nr": int(sample["sample_nr"]),
        "label": sample.get("user_label"),
        "stored": stored,
        "stored_limit": stored["c14_age_sig"] == LIMIT_AGE_SIGMA,
        "targets": [],
        "chosen": [],
        "mode": None,
        "result": None,
        "limit": False,
        "agreement": None,
        "message": None,
        "status": STATUS_SKIP,
    }
    unknown = [ref for ref in chosen_refs if ref not in by_ref]
    if unknown:
        raise ValueError(f"Target {unknown[0]} is not a target of sample {row['sample_nr']}.")
    not_measured = [ref for ref in chosen_refs if not is_measured(by_ref[ref])]
    chosen = [by_ref[ref] for ref in chosen_refs if is_measured(by_ref[ref])]
    row["chosen"] = [target_ref(t) for t in chosen]
    row["targets"] = [_target_row(t, magazine, set(row["chosen"])) for t in targets]
    if not measured:
        row["status"] = STATUS_NOT_MEASURED
        return row
    if not_measured:
        row["status"] = STATUS_INVALID
        row["message"] = f"Target {not_measured[0]} has no result yet."
        return row
    if not chosen:
        # Several measured targets and none ticked: still the operator's call.
        row["status"] = STATUS_CHOOSE if len(measured) > 1 else STATUS_SKIP
        return row
    try:
        outcome = single_result(chosen[0]) if len(chosen) == 1 else mean_result(chosen)
    except ValueError as exc:
        row["status"] = STATUS_INVALID
        row["message"] = str(exc)
        return row
    row["mode"] = "single" if len(chosen) == 1 else "mean"
    row["result"] = outcome["values"]
    row["limit"] = outcome["limit"]
    row["agreement"] = outcome["agreement"]
    if row["result"]["c14_age"] is None:
        row["status"] = STATUS_INVALID
        row["message"] = "The chosen target has no C14 age."
    elif stored["c14_age"] is None:
        row["status"] = STATUS_NEW
    elif _same(stored, row["result"]):
        row["status"] = STATUS_SAME
    else:
        row["status"] = STATUS_REPLACES
    return row


def _resolve(service: "SamsService", magazine: str) -> str:
    current = service.resolve_existing_magazine(magazine or "")
    if current is None:
        raise ValueError(f"Magazine {(magazine or '').strip() or '(empty)'} does not exist.")
    return current


def _read(service: "SamsService", magazine: str, choices: dict[int, list[str]]) -> dict[str, Any]:
    sources = service.transfer_sources(magazine)
    customers = [s for s in sources if not is_standard(s)]
    known = {int(s["sample_nr"]) for s in customers}
    stray = sorted(set(choices) - known)
    if stray:
        raise ValueError(f"Sample {stray[0]} is not measured in magazine {magazine}.")
    customers.sort(key=lambda s: _position_key(s, magazine))
    rows = [_sample_row(s, magazine, choices.get(int(s["sample_nr"]))) for s in customers]
    counts = {status: 0 for status in STATUS_ORDER}
    for row in rows:
        counts[row["status"]] += 1
    payload: dict[str, Any] = {
        "magazine": magazine,
        "rows": rows,
        "counts": counts,
        "standards": len(sources) - len(customers),
        "writes": counts[STATUS_NEW] + counts[STATUS_REPLACES],
        "refusal": None,
    }
    if not rows:
        payload["refusal"] = (
            f"Magazine {magazine} has no customer samples"
            + (" (only standards, which are not transferred)." if sources else ".")
        )
    return payload


def plan(service: "SamsService", magazine: str, choices_text: str | None = None) -> dict[str, Any]:
    """The dialog's preview (JSON) for the current ticks. Writes nothing."""
    return _read(service, _resolve(service, magazine), parse_choices(choices_text))


def apply(service: "SamsService", magazine: str, choices_text: str | None) -> str:
    """Read everything again, then write the new and differing results.
    Returns the toast; raises ValueError (nothing changed) otherwise."""
    current = _resolve(service, magazine)
    payload = _read(service, current, parse_choices(choices_text))
    if payload["refusal"]:
        raise ValueError(f"{payload['refusal']} {NOTHING_CHANGED}")
    changes = [
        {"sample_nr": row["sample_nr"], **row["result"]}
        for row in payload["rows"]
        if row["status"] in WRITES
    ]
    counts = payload["counts"]
    if not changes:
        if counts[STATUS_SAME]:
            return f"The results of magazine {current}'s samples are already up to date."
        raise ValueError(f"No sample has a result to transfer: tick a target for each sample first. {NOTHING_CHANGED}")
    written = service.transfer_sample_results(changes)
    means = sum(1 for row in payload["rows"] if row["status"] in WRITES and row["mode"] == "mean")
    parts = [f"{counts[STATUS_NEW]} new", f"{counts[STATUS_REPLACES]} replaced"]
    if means:
        parts.append(f"{means} as a mean")
    left = counts[STATUS_CHOOSE] + counts[STATUS_SKIP] + counts[STATUS_INVALID]
    if left:
        parts.append(f"{left} left as they were")
    return (
        f"Transferred results of {written} sample{'' if written == 1 else 's'} of magazine {current} "
        f"({', '.join(parts)})."
    )

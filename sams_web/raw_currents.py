"""Fetch LE / HE currents from the raw AMS databases (ADR-0011).

Each AMS writes its raw measurement data into its own database on the
same MariaDB server: `db_dc14` (AMS.03, magazines MA…) and `db_ac14`
(AMS.38, magazines MB…). Its `workfinal` table holds the final row per
target; `ANA` is the LE current, `A` the HE current. The legacy SAMS
copied them into `target_t.le_curr / he_curr` on its transfer step; here
the operator does that per magazine from Lab → Analysis.

The app reads the raw databases only through the `ams_raw_currents`
procedure in db_dmams (docs/sql/0011_ams_raw_currents.sql), and only from
this action's preview and fetch. They may be missing or unreadable at any
time: then the dialog says why and **nothing is changed** — no page, no
stored value and no backup depends on them.

Rules:
- Always preview, then fetch; the fetch reads the raw data again.
- A raw value that is empty or 0 is *no raw data*: it never overwrites or
  clears a stored current.
- Only new and differing values are written; a value that matches to two
  decimals (the raw values are rounded to two, as the legacy SAMS did)
  is *same*.
- Targets frozen in BATS (`editallowed = 2`) are written too: the currents
  are raw facts, not BATS results. The preview counts them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sams_web.repositories import AMS_RAW_SYSTEMS, RawDataError

if TYPE_CHECKING:
    from sams_web.services import SamsService


FIELDS = ("le_curr", "he_curr")
FROZEN = 2  # target_t.editallowed of a target BATS froze
NOTHING_CHANGED = "Nothing was changed."
SETUP_SCRIPT = "docs/sql/0011_ams_raw_currents.sql"

STATUS_NEW = "new"
STATUS_DIFFERS = "differs"
STATUS_SAME = "same"
STATUS_NO_RAW = "no_raw"
STATUS_ORDER = (STATUS_NEW, STATUS_DIFFERS, STATUS_SAME, STATUS_NO_RAW)


# ---- Problems: why the raw data could not be read -------------------------

_NOT_SET_UP = {1305}                       # procedure does not exist
_NO_EXECUTE = {1370}                       # app user may not run it (or it is missing)
_MISSING = {1049, 1146}                    # unknown database / table
_CHANGED = {1054}                          # unknown column
_NO_RIGHTS = {1142, 1143, 1044, 1449}      # definer lacks rights / is gone
_TOO_SLOW = {1969, 1205, 3024, 1317}       # statement / lock timeout, interrupted
_NO_SERVER = {2002, 2003, 2006, 2013}      # connection lost


def describe_problem(error: RawDataError, raw_db: str) -> dict[str, Any]:
    """Turn a failed raw read into what happened and what to do."""
    code = error.code
    if code in _NOT_SET_UP:
        title = "Not set up yet"
        advice = (
            f"The database has no ams_raw_currents procedure. A database administrator runs {SETUP_SCRIPT} "
            "in this database (see docs/server_installation.md)."
        )
    elif code in _NO_EXECUTE:
        # MariaDB answers "execute command denied" also for a procedure that
        # does not exist, when the app's user has no EXECUTE on the database:
        # it checks the right before it looks for the routine.
        title = "Not set up for the app"
        advice = (
            "The ams_raw_currents procedure does not exist yet, or the app's database user may not run it. "
            f"A database administrator runs {SETUP_SCRIPT} in this database, including the GRANT line at its end."
        )
    elif code in _MISSING:
        title = f"{raw_db} is not available"
        advice = (
            f"The raw database of this AMS, or its workfinal table, is missing or was renamed. "
            "Check it on the database server; the stored currents are kept as they are."
        )
    elif code in _CHANGED:
        title = f"{raw_db}.workfinal has changed"
        advice = (
            "A column the procedure reads (SAMPLE_NR, PREP_NR, TARGET_NR, RECNO, ANA, A) is missing. "
            f"Adapt {SETUP_SCRIPT} to the new table and run it again."
        )
    elif code in _NO_RIGHTS:
        title = f"No permission to read {raw_db}"
        advice = (
            "The procedure reads the raw databases with the rights of the account that created it. "
            f"Recreate it ({SETUP_SCRIPT}) as an account that may SELECT in db_dc14 and db_ac14."
        )
    elif code in _TOO_SLOW:
        title = f"{raw_db} is not answering"
        advice = (
            "Reading it took too long or its table was locked, for example while the AMS software writes to it. "
            "Try again in a few minutes."
        )
    elif code in _NO_SERVER:
        title = "The database server is not reachable"
        advice = "Check the network connection to the database server and try again."
    else:
        title = "Reading the raw AMS data failed"
        advice = "Show this message to whoever looks after the database server."
    return {"title": title, "advice": advice, "code": code, "detail": error.detail}


# ---- Comparing stored and raw values -------------------------------------

def raw_db_for(magazine: str) -> str | None:
    """The raw database of the AMS that measures this magazine."""
    return AMS_RAW_SYSTEMS.get((magazine or "").strip()[:2].upper())


def _usable(value: Any) -> float | None:
    """A raw value worth storing: empty and 0 mean *no raw data*."""
    if value is None:
        return None
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError):
        return None
    return number if number != 0 else None


def _same(stored: Any, raw: float) -> bool:
    if stored is None:
        return False
    try:
        return round(float(stored), 2) == raw
    except (TypeError, ValueError):
        return False


def compare(target: dict[str, Any], raw: dict[str, Any] | None) -> dict[str, Any]:
    """One target's row in the preview: stored and raw values, status and
    the fields a fetch would write."""
    writes: dict[str, float] = {}
    replaces = False
    raw_values: dict[str, float | None] = {}
    for field in FIELDS:
        value = _usable(raw.get(field)) if raw else None
        raw_values[field] = value
        if value is None or _same(target.get(field), value):
            continue
        writes[field] = value
        if target.get(field) is not None:
            replaces = True
    if all(value is None for value in raw_values.values()):
        status = STATUS_NO_RAW
    elif not writes:
        status = STATUS_SAME
    else:
        status = STATUS_DIFFERS if replaces else STATUS_NEW
    raw_rows = int(raw.get("raw_rows") or 0) if raw else 0
    return {
        "target_id": f"{target['sample_nr']}.{target['prep_nr']}.{target['target_nr']}",
        "sample_nr": target["sample_nr"],
        "prep_nr": target["prep_nr"],
        "target_nr": target["target_nr"],
        "position": target.get("position"),
        "label": target.get("user_label"),
        "stored": {field: target.get(field) for field in FIELDS},
        "raw": raw_values,
        "status": status,
        "writes": writes,
        "frozen": target.get("editallowed") == FROZEN,
        "raw_rows": raw_rows,
    }


# ---- Preview and fetch -----------------------------------------------------

def _resolve(service: "SamsService", magazine: str) -> str:
    current = service.resolve_existing_magazine(magazine or "")
    if current is None:
        raise ValueError(f"Magazine {(magazine or '').strip() or '(empty)'} does not exist.")
    return current


def _key(row: dict[str, Any]) -> tuple[int, int, int]:
    return (int(row["sample_nr"]), int(row["prep_nr"]), int(row["target_nr"]))


def _read(service: "SamsService", magazine: str) -> dict[str, Any]:
    """Compare the magazine's targets with the raw data. Never raises for
    the raw database: a failure comes back as `problem`."""
    raw_db = raw_db_for(magazine)
    targets = service.list_targets_by_magazine(magazine)
    payload: dict[str, Any] = {
        "magazine": magazine,
        "raw_db": raw_db,
        "rows": [],
        "counts": {status: 0 for status in STATUS_ORDER},
        "frozen_writes": 0,
        "several_rows": 0,
        "problem": None,
        "refusal": None,
    }
    if raw_db is None:
        prefixes = ", ".join(f"{prefix}… ({db})" for prefix, db in AMS_RAW_SYSTEMS.items())
        payload["refusal"] = f"Magazine {magazine} is not from an AMS with a raw database. Currents can be fetched for {prefixes} magazines."
        return payload
    if not targets:
        payload["refusal"] = f"Magazine {magazine} has no targets."
        return payload
    try:
        raw_rows = service.raw_currents_for_magazine(magazine)
    except RawDataError as exc:
        payload["problem"] = describe_problem(exc, raw_db)
        return payload
    raw_by_key = {_key(row): row for row in raw_rows}
    for target in targets:
        row = compare(target, raw_by_key.get(_key(target)))
        payload["rows"].append(row)
        payload["counts"][row["status"]] += 1
        if row["writes"] and row["frozen"]:
            payload["frozen_writes"] += 1
        if row["raw_rows"] > 1:
            payload["several_rows"] += 1
    if payload["counts"][STATUS_NO_RAW] == len(targets):
        payload["refusal"] = (
            f"None of its {len(targets)} target{'' if len(targets) == 1 else 's'} has currents in {raw_db} yet. "
            "Was the magazine measured and evaluated on the AMS?"
        )
    return payload


def plan(service: "SamsService", magazine: str) -> dict[str, Any]:
    """The dialog's preview (JSON). Writes nothing."""
    payload = _read(service, _resolve(service, magazine))
    payload["writes"] = sum(1 for row in payload["rows"] if row["writes"])
    return payload


def apply(service: "SamsService", magazine: str) -> str:
    """Read the raw data again and store new / differing currents.
    Returns the notice for the toast; raises ValueError (nothing changed)
    when the raw data cannot be read or there is nothing to fetch."""
    current = _resolve(service, magazine)
    payload = _read(service, current)
    if payload["problem"]:
        problem = payload["problem"]
        raise ValueError(f"{problem['title']}. {problem['advice']} {NOTHING_CHANGED}")
    if payload["refusal"]:
        raise ValueError(f"{payload['refusal']} {NOTHING_CHANGED}")
    changes = [
        {"sample_nr": row["sample_nr"], "prep_nr": row["prep_nr"], "target_nr": row["target_nr"], **row["writes"]}
        for row in payload["rows"]
        if row["writes"]
    ]
    if not changes:
        return f"The currents of magazine {current} are already up to date."
    written = service.fetch_raw_currents(changes)
    counts = payload["counts"]
    parts = [f"{counts[STATUS_NEW]} new", f"{counts[STATUS_DIFFERS]} replaced"]
    if counts[STATUS_NO_RAW]:
        parts.append(f"{counts[STATUS_NO_RAW]} without raw data")
    return (
        f"Fetched LE/HE currents for {written} target{'' if written == 1 else 's'} of magazine {current} "
        f"from {payload['raw_db']} ({', '.join(parts)})."
    )

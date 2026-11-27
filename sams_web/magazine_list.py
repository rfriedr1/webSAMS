"""The magazine list on Lab → Analysis.

Beside the chosen magazine's targets the Magazine panel lists the magazines
the lab worked on last, newest `magazine_t.last_changed` first, so nobody
has to know a magazine's name to open it (the legacy SAMS's "recent
magazines" list, whose length was a spin box on the form). How many are
listed is Setup → *Analysis* (`analysis.magazine_limit`, default 200).

The list is capped, so its table filter only searches the rows shown. The
magazine field above it searches **all** magazines: a name that matches no
magazine exactly lists every magazine containing it (`find`), still newest
first and still capped, and the count line says how many there are.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from sams_web.setup_sections import SETUP_SECTION_ANALYSIS

if TYPE_CHECKING:
    from sams_web.services import SamsService
    from sams_web.setup_store import SetupStore


DEFAULT_MAGAZINE_LIMIT = 200
MIN_MAGAZINE_LIMIT = 10
MAX_MAGAZINE_LIMIT = 5000

class AnalysisSettingsStore:
    """Setup section `analysis`: `{"magazine_limit": 200}`."""

    section_key = SETUP_SECTION_ANALYSIS

    def __init__(self, setup_store: "SetupStore") -> None:
        self._store = setup_store

    def load(self) -> dict[str, int]:
        raw = self._store.get_section(self.section_key, default={})
        value = raw.get("magazine_limit") if isinstance(raw, dict) else None
        try:
            limit = int(value)
        except (TypeError, ValueError):
            limit = DEFAULT_MAGAZINE_LIMIT
        return {"magazine_limit": min(max(limit, MIN_MAGAZINE_LIMIT), MAX_MAGAZINE_LIMIT)}

    def update(self, payload: dict[str, Any]) -> dict[str, int]:
        text = str(payload.get("magazine_limit") or "").strip()
        try:
            limit = int(text)
        except ValueError:
            raise ValueError("Enter how many magazines to list as a whole number, e.g. 200.") from None
        if not MIN_MAGAZINE_LIMIT <= limit <= MAX_MAGAZINE_LIMIT:
            raise ValueError(
                f"List between {MIN_MAGAZINE_LIMIT} and {MAX_MAGAZINE_LIMIT} magazines (you entered {limit})."
            )
        raw = self._store.get_section(self.section_key, default={})
        cleaned = {**(raw if isinstance(raw, dict) else {}), "magazine_limit": limit}
        self._store.set_section(self.section_key, cleaned)
        return {"magazine_limit": limit}


def analysis_href(magazine: str = "", find: str = "", include_standards: bool = False) -> str:
    """Lab → Analysis with a magazine open, the list filtered and/or the
    standards switch on — the page's three query parameters, kept together."""
    params: dict[str, str] = {}
    if magazine:
        params["magazine"] = magazine
    if find:
        params["find"] = find
    if include_standards:
        params["include_standards"] = "true"
    return "/lab/analysis" + (f"?{urlencode(params)}" if params else "")


def measured_text(targets: int, measured: int) -> str:
    """The list's status line in words (a status is never colour alone)."""
    if targets == 0:
        return "no targets yet"
    if measured == 0:
        return f"{targets} target{'' if targets == 1 else 's'}, not measured"
    if measured == targets:
        return f"{targets} measured"
    return f"{measured} of {targets} measured"


def _row(row: dict[str, Any], href: str) -> dict[str, Any]:
    targets = int(row.get("target_count") or 0)
    measured = int(row.get("measured_targets") or 0)
    return {
        "magazine": row["magazine"],
        "href": href,
        "target_count": targets,
        "measured_targets": measured,
        "measured_text": measured_text(targets, measured),
        "state": "empty" if targets == 0 else "done" if measured == targets else "open" if measured == 0 else "partly",
    }


def build_magazine_list(
    service: "SamsService",
    *,
    current: str,
    find: str,
    include_standards: bool,
) -> dict[str, Any]:
    """Everything the list needs: rows, counts, and a link per magazine that
    keeps the name search and the standards switch."""
    limit = AnalysisSettingsStore(service.setup_store).load()["magazine_limit"]
    find = find.strip()
    rows = [
        _row(row, analysis_href(str(row["magazine"]), find, include_standards) + "#tbl-magazine-targets")
        for row in service.list_recent_magazines(limit, find or None)
    ]
    total = service.count_magazines(find or None)
    return {
        "rows": rows,
        "limit": limit,
        "total": total,
        "capped": total > len(rows),
        "find": find,
        "current": current,
        "clear_find_href": analysis_href(current, "", include_standards) + "#tbl-magazine-targets",
    }

"""Global search: per-context SQL config + display link rules + executor.

Replaces the split definition that previously lived as `SearchContext` /
`SEARCH_CONTEXTS` / `global_search` in `repositories.py` and a chained `if/elif`
cell-link block in `templates/search.html`.

A `SearchContext` is **just data plus a function**: which DB table to query,
which columns participate in the LIKE-match, and a `link_for(column, row)`
function that decides whether a given cell becomes a link (and to where).

The shared `fk_based_link` rule expresses the "entity-rooted columns become
links to the matching detail page" convention used by every existing context
today; it's exposed as a public helper so future contexts (e.g. Magazine
search, when that arrives) can reuse it or supply their own.

`run_search(session, context_name, phrase, limit)` is the single entry point
the service layer calls.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.orm import Session


LinkRule = Callable[[str, Mapping[str, Any]], "str | None"]


# ---- Default link rule ----------------------------------------------------


def fk_based_link(column: str, row: Mapping[str, Any]) -> str | None:
    """Return a detail-page URL for `column` based on the FK columns in `row`.

    Convention shared by all entity-rooted contexts:

    - `sample_nr` column → `/samples/<sample_nr>`
    - `project_nr` or `project` column → `/projects/<project_nr>`
    - `user_nr` or `last_name` column → `/submitters/<user_nr>`
    - `prep_nr` column (with `sample_nr` in row) → `/samples/<sample_nr>/preparations/<prep_nr>`
    - `target_nr` or `c14_age` column (with sample/prep/target FK in row) →
      `/samples/<sample_nr>/preparations/<prep_nr>/targets/<target_nr>`

    Returns `None` for columns that have no entity-detail link.
    """
    sample_nr = row.get("sample_nr")
    project_nr = row.get("project_nr")
    user_nr = row.get("user_nr")
    prep_nr = row.get("prep_nr")
    target_nr = row.get("target_nr")
    column_lower = column.lower()

    if column_lower == "sample_nr" and sample_nr is not None:
        return f"/samples/{sample_nr}"
    if column_lower in ("project_nr", "project") and project_nr is not None:
        return f"/projects/{project_nr}"
    if column_lower in ("user_nr", "last_name") and user_nr is not None:
        return f"/submitters/{user_nr}"
    if column_lower == "prep_nr" and sample_nr is not None and prep_nr is not None:
        return f"/samples/{sample_nr}/preparations/{prep_nr}"
    if column_lower in ("target_nr", "c14_age") and sample_nr is not None and prep_nr is not None and target_nr is not None:
        return f"/samples/{sample_nr}/preparations/{prep_nr}/targets/{target_nr}"
    return None


# ---- SearchContext --------------------------------------------------------


@dataclass(frozen=True)
class SearchContext:
    """Definition of one global-search context.

    `fields` participate in the LIKE-match (joined via `CONCAT_WS(';', ...)`).
    SELECT * returns all table columns to the template; `fields` is only the
    matching surface, not the display column list.
    """

    name: str
    table: str
    fields: tuple[str, ...]
    link_for: LinkRule = fk_based_link


SEARCH_CONTEXTS: dict[str, SearchContext] = {
    "submitters": SearchContext(
        name="submitters",
        table="user_t",
        fields=(
            "user_nr",
            "last_name",
            "first_name",
            "organisation",
            "address_1",
            "address_2",
            "town",
            "country",
            "institute",
            "postcode",
            "phone_1",
            "phone_2",
            "email",
            "account",
            "user_comment",
        ),
    ),
    "projects": SearchContext(
        name="projects",
        table="project_t",
        fields=(
            "project_nr",
            "project",
            "user_nr",
            "in_date",
            "out_date",
            "invoice",
            "AuftragsNr",
            "order_nr",
            "invoice_nr",
            "letter",
            "project_comment",
            "report",
            "sample_storage_loc",
        ),
    ),
    "samples": SearchContext(
        name="samples",
        table="sample_t",
        fields=(
            "sample_nr",
            "project_nr",
            "type",
            "material",
            "fraction",
            "weight",
            "sampling_date",
            "user_label",
            "user_label_nr",
            "user_desc1",
            "user_desc2",
            "MA_nr",
            "lab_comment",
            "user_comment",
            "prep_storage_loc",
            "storage",
        ),
    ),
    "preparations": SearchContext(
        name="preparations",
        table="preparation_t",
        fields=(
            "sample_nr",
            "prep_nr",
            "batch",
            "cn_ratio",
            "c_percent",
            "n_percent",
            "prep_end",
            "prep_start",
            "prep_comment",
        ),
    ),
    "targets": SearchContext(
        name="targets",
        table="target_t",
        fields=(
            "sample_nr",
            "target_nr",
            "prep_nr",
            "magazine",
            "position",
            "target_comment",
            "meas_comment",
            "graph_batch",
            "weight",
            "conc_c",
            "target_id",
        ),
    ),
}


# ---- Executor -------------------------------------------------------------


def run_search(
    session: Session,
    context_name: str,
    phrase: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Run the global-search SQL for the named context.

    Raises `ValueError` if `context_name` is not a registered context.
    """
    context = SEARCH_CONTEXTS.get(context_name)
    if context is None:
        raise ValueError(f"Unsupported search context: {context_name}")

    concat_fields = ",".join(context.fields)
    stmt = text(
        f"""
        SELECT *
        FROM {context.table}
        WHERE CONCAT_WS(';',{concat_fields}) LIKE :phrase
        LIMIT :limit
        """
    )
    rows = session.execute(stmt, {"phrase": f"%{phrase}%", "limit": limit}).mappings().all()
    return [dict(row) for row in rows]


__all__ = [
    "SearchContext",
    "SEARCH_CONTEXTS",
    "fk_based_link",
    "LinkRule",
    "run_search",
]

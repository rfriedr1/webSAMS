"""Small helpers for the sample detail-page route.

The per-entity context builders that previously lived here have moved to
`sams_web.detail_page` (the generic builder) and the per-entity
`*_DETAIL_PAGE` configs in the viewmodel modules. The only remaining
helper is the sample creation notice, which is purely a query-param-to-
text transformation that doesn't fit elsewhere.
"""

from __future__ import annotations


def build_sample_creation_notice(
    *,
    created: str | None,
    created_prep: int | None,
    created_target: int | None,
) -> str | None:
    if created == "prep" and created_prep is not None:
        return f"Created preparation #{created_prep} and seeded target #1."
    if created == "target" and created_prep is not None and created_target is not None:
        return f"Created target #{created_target} in preparation #{created_prep}."
    return None

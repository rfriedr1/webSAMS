"""Match parsed values against records that already exist in the DB.

Two jobs:

1. **Submitter matching.** Most submissions come from returning
   customers, and creating a duplicate `user_t` row splits their project
   history. Legacy matched on `last_name` with a *partial key* — so
   "Meyer" silently matched "Meyerhoff" and the operator often bound the
   project to the wrong person. Here, candidates are scored across
   e-mail, name and organisation, and the operator always sees and
   confirms the choice.

2. **Lookup resolution.** `material` / `type` / `fraction` are
   free text on the sheet but constrained lists in the DB. Exact matches
   are applied automatically; anything else becomes a *suggestion* for
   the operator rather than a guess, because silently coercing
   "collagen" to "collagen user prep." would corrupt the record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from sams_web.sample_import.vocabulary import (
    match_choice,
    normalize_label,
    suggest_from_choices,
)

#: Score at or above which a submitter match is offered pre-selected.
#: An e-mail hit alone clears this; a name-only hit deliberately does not.
STRONG_MATCH_SCORE = 0.9

#: Below this we do not bother showing the candidate at all.
MIN_CANDIDATE_SCORE = 0.55

MAX_CANDIDATES = 8


@dataclass
class SubmitterCandidate:
    """An existing `user_t` row that might be the sheet's submitter."""

    user_nr: int
    display_name: str
    organisation: str
    email: str
    town: str
    score: float
    #: Short human explanation of *why* this matched, shown in the UI so
    #: the operator can judge the suggestion rather than trust it blindly.
    reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "user_nr": self.user_nr,
            "display_name": self.display_name,
            "organisation": self.organisation,
            "email": self.email,
            "town": self.town,
            "score": round(self.score, 3),
            "reasons": list(self.reasons),
            "is_strong": self.score >= STRONG_MATCH_SCORE,
        }


def _text(value: object) -> str:
    return "" if value is None else str(value).strip()


def score_submitter(parsed: dict[str, str], row: Any) -> tuple[float, list[str]]:
    """Score one existing submitter against the parsed contact block.

    Weighting reflects how identifying each signal actually is:
    e-mail is near-unique, so an exact hit is decisive on its own;
    surname alone is weak (many Müllers); surname + organisation is
    strong; a first-name match adds confidence but never carries a match
    by itself.
    """
    score = 0.0
    reasons: list[str] = []

    parsed_email = normalize_label(parsed.get("email", ""))
    row_email = normalize_label(_text(row.email))
    if parsed_email and row_email and parsed_email == row_email:
        score += 0.90
        reasons.append("e-mail matches")

    parsed_last = normalize_label(parsed.get("last_name", ""))
    row_last = normalize_label(_text(row.last_name))
    last_matches = bool(parsed_last) and parsed_last == row_last
    if last_matches:
        score += 0.30
        reasons.append("surname matches")

    parsed_first = normalize_label(parsed.get("first_name", ""))
    row_first = normalize_label(_text(row.first_name))
    if parsed_first and row_first and parsed_first == row_first:
        score += 0.25
        reasons.append("first name matches")

    parsed_org = normalize_label(parsed.get("organisation", ""))
    row_org = normalize_label(_text(row.organisation))
    if parsed_org and row_org:
        if parsed_org == row_org:
            score += 0.30
            reasons.append("organisation matches")
        elif parsed_org in row_org or row_org in parsed_org:
            score += 0.15
            reasons.append("organisation is similar")

    parsed_town = normalize_label(parsed.get("town", ""))
    row_town = normalize_label(_text(row.town))
    if parsed_town and row_town and parsed_town == row_town:
        score += 0.05
        reasons.append("town matches")

    # Surname + organisation without an e-mail is still a confident
    # match in practice; nudge it over the strong threshold.
    if last_matches and "organisation matches" in reasons and not parsed_email:
        score += 0.10

    return min(score, 1.0), reasons


def find_submitter_candidates(
    parsed: dict[str, str], rows: Sequence[Any]
) -> list[SubmitterCandidate]:
    """Rank existing submitters against the parsed contact block."""
    scored: list[SubmitterCandidate] = []
    for row in rows:
        score, reasons = score_submitter(parsed, row)
        if score < MIN_CANDIDATE_SCORE:
            continue
        last = _text(row.last_name)
        first = _text(row.first_name)
        scored.append(
            SubmitterCandidate(
                user_nr=int(row.user_nr),
                display_name=f"{last}, {first}".strip(", ") or "(unnamed)",
                organisation=_text(row.organisation),
                email=_text(row.email),
                town=_text(row.town),
                score=score,
                reasons=reasons,
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[:MAX_CANDIDATES]


def candidate_search_terms(parsed: dict[str, str]) -> list[str]:
    """Terms worth querying the DB with to gather candidates.

    We cannot score every submitter in the database, so this narrows to
    a shortlist first. Surname and organisation are the useful handles;
    e-mail is matched separately with an exact query.
    """
    terms: list[str] = []
    for key in ("last_name", "organisation"):
        value = parsed.get(key, "").strip()
        if len(value) >= 2:
            terms.append(value)
    return terms


@dataclass
class LookupResolution:
    """Outcome of resolving one free-text value against a lookup list."""

    raw: str
    resolved: str | None            #: exact hit, applied automatically
    suggestions: list[str]          #: near misses for the operator

    @property
    def needs_attention(self) -> bool:
        return self.resolved is None and bool(self.raw)

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "resolved": self.resolved,
            "suggestions": list(self.suggestions),
            "needs_attention": self.needs_attention,
        }


def resolve_lookup_value(raw: object, choices: Iterable[str]) -> LookupResolution:
    """Resolve one free-text lookup value (material / type / fraction)."""
    options = list(choices)
    text = "" if raw is None else str(raw).strip()
    if not text:
        return LookupResolution(raw="", resolved=None, suggestions=[])
    exact = match_choice(text, options)
    if exact is not None:
        return LookupResolution(raw=text, resolved=exact, suggestions=[])
    suggestions = [choice for choice, _ in suggest_from_choices(text, options)]
    return LookupResolution(raw=text, resolved=None, suggestions=suggestions)


def resolve_lookup_column(
    values: Iterable[object], choices: Iterable[str]
) -> dict[str, LookupResolution]:
    """Resolve every distinct value in a lookup column once.

    Keyed by the raw text, so a sheet with 40 rows of 'charcoal' asks
    the operator about it a single time. This is the main ergonomic win
    over the legacy wizard, which required assigning a material to every
    row by hand.
    """
    options = list(choices)
    resolutions: dict[str, LookupResolution] = {}
    for value in values:
        text = "" if value is None else str(value).strip()
        if not text or text in resolutions:
            continue
        resolutions[text] = resolve_lookup_value(text, options)
    return resolutions


__all__ = [
    "MIN_CANDIDATE_SCORE",
    "STRONG_MATCH_SCORE",
    "LookupResolution",
    "SubmitterCandidate",
    "candidate_search_terms",
    "find_submitter_candidates",
    "resolve_lookup_column",
    "resolve_lookup_value",
    "score_submitter",
]

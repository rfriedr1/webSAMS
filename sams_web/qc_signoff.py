"""Generic QC sign-off: a supervisor reviews a set of QC results and signs.

ISO 17025 wants evidence that QC results were reviewed by someone
responsible. Today the reviewed things are EA checks; later they will be
the OXA2 scatter, blanks and IAEA standards. So the engine knows nothing
about any one of them — each kind is a `SignoffSubject` handler (same
pattern as `SetupSectionHandler`):

* `subject_type` / `item_type` — stored in `qc_signoff_t` / `qc_signoff_item_t`;
* `items(service, key, until)` — the candidate items of one subject key
  (e.g. 'ea1|acetanilide'), oldest first, voided ones excluded;
* `summarize(service, key, items)` — the statistics snapshot (stored as
  `stats_json`, so each kind keeps what it needs without new columns);
* `describe(service, key)` and `body_context(...)` + `body_template` —
  how the review / print view shows it.

The engine owns validation, the single transaction, "signed at most once"
(`qc_signoff_item_t` has a unique key on the item) and the history.

**Adding a subject (OXA2, blanks …):** one handler + one template part,
registered in `signoff_subjects()`. No DDL.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from sqlalchemy.exc import IntegrityError

from sams_web.lab_staff import LabStaffStore

if TYPE_CHECKING:  # pragma: no cover
    from sams_web.models import QcSignoff
    from sams_web.services import SamsService


VERDICTS: tuple[tuple[str, str], ...] = (
    ("accepted", "Accepted"),
    ("accepted_remarks", "Accepted with remarks"),
    ("rejected", "Rejected"),
)
VERDICT_LABELS = dict(VERDICTS)
COMMENT_MAX_LENGTH = 500


@dataclass(frozen=True)
class SignoffItem:
    ref: str  # stored as qc_signoff_item_t.item_ref
    at: datetime
    flagged: bool  # failed / out of limits
    record: Any = None


class SignoffSubject:
    subject_type: str = ""
    item_type: str = ""
    label: str = ""
    body_template: str = ""
    return_url: str = "/"

    def describe(self, service: "SamsService", key: str) -> str:
        return key

    def items(self, service: "SamsService", key: str, until: datetime | None = None) -> list[SignoffItem]:
        raise NotImplementedError

    def summarize(self, service: "SamsService", key: str, items: Sequence[SignoffItem]) -> dict[str, Any]:
        raise NotImplementedError

    def body_context(
        self, service: "SamsService", key: str, item_refs: Sequence[str], stats: Mapping[str, Any]
    ) -> dict[str, Any]:
        return {}


def signoff_subjects() -> dict[str, SignoffSubject]:
    """The registry. Imported lazily because subject modules import this one."""
    from sams_web.ea_checks import EaCheckSignoffSubject

    subjects: list[SignoffSubject] = [EaCheckSignoffSubject()]
    return {s.subject_type: s for s in subjects}


@dataclass
class SignOutcome:
    success: bool
    message: str = ""
    error: str | None = None
    signoff: "QcSignoff | None" = None


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


class QcSignoffs:
    def __init__(self, service: "SamsService", *, now: datetime | None = None) -> None:
        self.service = service
        self.repo = service.repo
        self._now = now

    def now(self) -> datetime:
        return self._now or datetime.now().replace(microsecond=0)

    def unsigned(self, subject: SignoffSubject, key: str, until: datetime | None = None) -> list[SignoffItem]:
        items = subject.items(self.service, key, until)
        signed = self.repo.signed_item_refs(subject.item_type, [i.ref for i in items])
        return [i for i in items if i.ref not in signed]

    def sign(
        self,
        *,
        subject_type: str,
        subject_key: str,
        period_to: str,
        signer: str,
        verdict: str,
        comment: str,
    ) -> SignOutcome:
        subject = signoff_subjects().get(subject_type)
        if subject is None:
            return SignOutcome(False, error=f"Unknown sign-off type '{subject_type}'.")
        signers = LabStaffStore(self.service.setup_store).signers()
        if not signers:
            return SignOutcome(
                False, error="Nobody may sign off yet — mark a supervisor in Setup → Lab Staff."
            )
        signer = signer.strip()
        if signer not in signers:
            return SignOutcome(False, error="Pick a supervisor allowed to sign off (Setup → Lab Staff).")
        if verdict not in VERDICT_LABELS:
            return SignOutcome(False, error="Pick a verdict.")
        comment = comment.strip()
        if verdict != "accepted" and not comment:
            return SignOutcome(False, error=f"'{VERDICT_LABELS[verdict]}' needs a comment.")
        if len(comment) > COMMENT_MAX_LENGTH:
            return SignOutcome(False, error=f"Comment is longer than {COMMENT_MAX_LENGTH} characters.")
        try:
            until = datetime.fromisoformat(period_to.strip()) if period_to.strip() else None
        except ValueError:
            return SignOutcome(False, error="The reviewed period is invalid — reload the page and try again.")
        # Only what the supervisor saw: items up to the reviewed end, so a
        # check logged while the review dialog was open is not swept in.
        items = self.unsigned(subject, subject_key, until)
        if not items:
            return SignOutcome(False, error="Nothing left to sign off — the set was signed in the meantime.")
        stats = subject.summarize(self.service, subject_key, items)
        payload = {
            "subject_type": subject.subject_type,
            "subject_key": subject_key,
            "period_from": items[0].at,
            "period_to": items[-1].at,
            "n_items": len(items),
            "n_flagged": sum(1 for i in items if i.flagged),
            "stats_json": json.dumps(stats, default=_json_default, sort_keys=True),
            "verdict": verdict,
            "signed_by": signer,
            "signed_at": self.now(),
            "comment": comment or None,
        }
        try:
            signoff = self.repo.create_qc_signoff(
                payload, item_type=subject.item_type, item_refs=[i.ref for i in items]
            )
            self.service.session.commit()
        except IntegrityError:
            self.service.session.rollback()
            return SignOutcome(False, error="Some of these items were signed in the meantime — reload and review again.")
        label = subject.describe(self.service, subject_key)
        return SignOutcome(
            True,
            message=f"{label}: {len(items)} items signed off by {signer} ({VERDICT_LABELS[verdict]}).",
            signoff=signoff,
        )

    def _row(self, signoff: "QcSignoff", subjects: Mapping[str, SignoffSubject]) -> dict[str, Any]:
        subject = subjects.get(signoff.subject_type)
        try:
            stats = json.loads(signoff.stats_json or "{}")
        except json.JSONDecodeError:
            stats = {}
        return {
            "id": signoff.id,
            "subject_type": signoff.subject_type,
            "subject_label": subject.label if subject else signoff.subject_type,
            "subject_key": signoff.subject_key,
            "description": subject.describe(self.service, signoff.subject_key) if subject else signoff.subject_key,
            "period_from": signoff.period_from,
            "period_to": signoff.period_to,
            "n_items": signoff.n_items,
            "n_flagged": signoff.n_flagged,
            "verdict": signoff.verdict,
            "verdict_label": VERDICT_LABELS.get(signoff.verdict, signoff.verdict),
            "signed_by": signoff.signed_by,
            "signed_at": signoff.signed_at,
            "comment": signoff.comment or "",
            "stats": stats,
        }

    def history(self, *, subject_type: str | None = None) -> list[dict[str, Any]]:
        subjects = signoff_subjects()
        return [self._row(s, subjects) for s in self.repo.list_qc_signoffs(subject_type=subject_type)]

    def detail(self, signoff_id: int) -> dict[str, Any] | None:
        signoff = self.repo.get_qc_signoff(signoff_id)
        if signoff is None:
            return None
        subjects = signoff_subjects()
        row = self._row(signoff, subjects)
        subject = subjects.get(signoff.subject_type)
        refs = self.repo.list_qc_signoff_item_refs(signoff.id)
        row["item_refs"] = refs
        row["body_template"] = subject.body_template if subject else ""
        row["return_url"] = subject.return_url if subject else "/"
        row["body"] = subject.body_context(self.service, signoff.subject_key, refs, row["stats"]) if subject else {}
        return row

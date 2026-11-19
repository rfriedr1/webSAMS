"""Photo bench: photograph samples with a webcam and file the pictures.

Samples are photographed after the import, before they go into the lab
(and now and then while they are processed). The page shows the webcam's
live feed; the operator takes a shot, the browser reads the label's
QR / DataMatrix code in it and the bench *suggests* the sample number,
which the operator acknowledges before anything is saved. Without a
readable label the number is typed or scanned, like on the other benches.

This module owns the read side (`PhotoBench.page_view` / `facts_view`)
and the label rule (`sample_nr_from_label`, mirrored by `labelSampleNr`
in `static/js/photo-bench.js`). Saving goes straight to
`SamplePhotos.save_new` — the bench writes files, never the database.
Design: `docs/adr/0010-photo-bench-writes-photo-share.md`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sams_web.services import SamsService


#: What one save may carry. A webcam JPEG is 0.3–2 MB; a file added from a
#: phone can be larger.
MAX_PHOTOS_PER_SAVE = 10
MAX_PHOTO_BYTES = 20 * 1024 * 1024
JPEG_MAGIC = b"\xff\xd8\xff"

#: `MAMS-48211`, `MAMS 48211`, `MAMS:48211` — the lab number as written on
#: reports and e-mails. Checked before the bare-number rule.
_MAMS_NUMBER = re.compile(r"MAMS[\s:_-]*0*(\d{1,7})\b", re.IGNORECASE)
_DIGIT_RUN = re.compile(r"\d+")
#: A label number shorter than this is more likely a counter or a date part.
_MIN_LABEL_DIGITS = 3


def sample_nr_from_label(text: str | None) -> int | None:
    """The sample number a decoded label code names, or None.

    Accepts the number alone (`48211`, `048211`), the `MAMS-48211` form,
    or a text with exactly one run of 3+ digits (`Sample 48211`). Anything
    else — several numbers, none — is not guessed at.
    """
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.isdigit():
        number = int(cleaned)
        return number if number > 0 else None
    match = _MAMS_NUMBER.search(cleaned)
    if match is not None:
        return int(match.group(1)) or None
    runs = [run for run in _DIGIT_RUN.findall(cleaned) if len(run) >= _MIN_LABEL_DIGITS]
    if len(runs) == 1:
        return int(runs[0]) or None
    return None


def parse_sample_nr(raw: str | None) -> int | None:
    """A typed or scanned Sample #: digits only, after trimming."""
    cleaned = (raw or "").strip()
    if not cleaned.isdigit():
        return None
    number = int(cleaned)
    return number if number > 0 else None


def is_jpeg(data: bytes) -> bool:
    return data[:3] == JPEG_MAGIC


class PhotoBench:
    """Read side of the photo bench page."""

    def __init__(self, service: "SamsService") -> None:
        self.service = service
        self.repo = service.repo

    def load_entry(self, sample_nr: int) -> dict[str, Any] | None:
        sample = self.repo.get_sample(sample_nr)
        if sample is None:
            return None
        project = self.repo.get_project(sample.project_nr) if sample.project_nr else None
        user = self.repo.get_submitter(project.user_nr) if project and project.user_nr else None
        return {"sample": sample, "project": project, "user": user}

    def facts_view(self, *, sample_nr_raw: str | None = None, label: str | None = None) -> dict[str, Any]:
        """Context for `_photo_bench_facts.html`: one sample's facts, or why
        there are none. `label` is decoded label text (the suggestion card);
        `sample_nr_raw` a typed or scanned number."""
        from_label = label is not None and label.strip() != ""
        sample_nr = sample_nr_from_label(label) if from_label else parse_sample_nr(sample_nr_raw)
        entry = self.load_entry(sample_nr) if sample_nr is not None else None
        error: str | None = None
        if from_label and sample_nr is None:
            error = "The label does not name a sample number."
        elif sample_nr is None and (sample_nr_raw or "").strip():
            error = f"“{(sample_nr_raw or '').strip()}” is not a sample number."
        elif sample_nr is not None and entry is None:
            error = f"There is no sample {sample_nr}."
        return {
            "photo_bench_entry": entry,
            "photo_sample_nr": sample_nr,
            "photo_error": error,
            "photo_from_label": from_label,
            "photo_label_text": (label or "").strip() if from_label else "",
        }

    def page_view(self, *, sample_nr_raw: str | None) -> dict[str, Any]:
        facts = self.facts_view(sample_nr_raw=sample_nr_raw)
        return {
            "title": "Photo bench",
            "photo_sample_query": (sample_nr_raw or "").strip(),
            "photo_max_files": MAX_PHOTOS_PER_SAVE,
            "photo_max_mb": MAX_PHOTO_BYTES // (1024 * 1024),
            **facts,
        }

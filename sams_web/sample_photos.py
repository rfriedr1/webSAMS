"""Sample photos: image files on a shared folder, found by file name.

Every sample is photographed on receipt and the pictures are dropped into
one folder on the lab's file server. There is no database link — a file
belongs to a sample because its name *starts with the sample number*
(`48211.jpg`, `48211b.jpg`, `48211_back.png`, ...). The legacy Delphi app
globbed `<sample_nr>*.jpg`, which also matched `482110.jpg` for sample
48211; here the number must end at a non-digit.

A *group photo* shows several samples at once and names them all:
`25328-25337.jpg` (a range), `16191_16192.jpg`, `12419-12420-12423.jpg`
(lists). It is listed on every sample it names — see
`sample_nrs_from_filename` for exactly which spellings count.

Three pieces:

- `SamplePhotoSettingsStore` — the folder, stored in the generic setup file
  (Setup -> *Sample Photos*).
- `SamplePhotoLibrary` — an in-memory index `sample_nr -> files`, built by
  walking the folder in a background thread. A network share can take
  seconds to list and can hang outright when the drive is gone, so no
  request ever waits on the filesystem for longer than `wait_seconds`;
  it gets a `scanning` answer instead and the browser asks again.
- `SamplePhotos` — what the routes talk to: list the photos of one
  sample, resolve one of them to a real path for serving.

Nothing here touches the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time
from typing import Any
from urllib.parse import quote

from sams_web.setup_store import SetupStore


logger = logging.getLogger(__name__)

SETUP_SECTION_SAMPLE_PHOTOS = "sample_photos"

#: Formats every current browser renders inline.
VIEWABLE_EXTENSIONS: frozenset[str] = frozenset({".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"})
#: Image formats browsers cannot show. They are still listed, as
#: download-only tiles, so a TIFF from the microscope is not invisible.
DOWNLOAD_ONLY_EXTENSIONS: frozenset[str] = frozenset({".tif", ".tiff", ".heic", ".heif"})
PHOTO_EXTENSIONS: frozenset[str] = VIEWABLE_EXTENSIONS | DOWNLOAD_ONLY_EXTENSIONS

#: Leading sample number, plus any further numbers chained straight onto it
#: with `-`, `_` or `+`. The greedy `\d+` takes the whole digit run, so
#: sample 48211 never claims `482110.jpg`; what follows the chain may be
#: anything (`b`, ` (1)`, `_ersatz`, `.`).
_LEADING_NUMBER_CHAIN = re.compile(r"\d+(?:[-_+]\d+)*")

#: A group photo covers neighbouring samples of one delivery. Anything
#: further apart than this is not a second sample number but something
#: else that happens to be numeric (a date, a customer's own label).
GROUP_MAX_SPAN = 100

STATE_OK = "ok"
STATE_NOT_CONFIGURED = "not_configured"
STATE_SCANNING = "scanning"
STATE_UNAVAILABLE = "unavailable"


def sample_nrs_from_filename(filename: str) -> tuple[int, ...]:
    """Every sample a photo file belongs to, judged by its name alone.

    The name must start with a sample number; that number always counts.
    Leading zeros are tolerated (`00482.jpg` is sample 482). Hidden files
    (`.DS_Store`, macOS `._48211.jpg` resource forks) never match because
    they do not start with a digit.

    Further numbers joined directly to the first make it a group photo
    when they lie within `GROUP_MAX_SPAN` of it:

    - `25328-25337.jpg`            -> the range 25328 ... 25337
    - `11584-7.jpg`, `14518-20.jpg` -> the range 11584 ... 11587 / 14520:
                                      a short number after a *dash* replaces
                                      the last digits (lab convention)
    - `16191_16192.jpg`, `16881+16882b.jpg`, `12419-12420-12423.jpg`
                                   -> each number listed; these must be
                                      written out in full

    Everything else stays with the first sample only: `36231_2.jpg` is
    "photo 2 of 36231" (an underscore never abbreviates), and
    `11813-2.jpg` would end below where it starts, so it is not a range.
    """
    if Path(filename).suffix.lower() not in PHOTO_EXTENSIONS:
        return ()
    match = _LEADING_NUMBER_CHAIN.match(filename)
    if match is None:
        return ()
    chain = match.group(0)
    first, *rest = (int(part) for part in re.split(r"[-_+]", chain))
    width = len(str(first))
    dash_pair = re.fullmatch(r"\d+-(\d+)", chain)
    if dash_pair is not None:
        last = _abbreviated_range_end(first, dash_pair.group(1))
        if last is not None:
            return tuple(range(first, last + 1))
    others = [
        nr for nr in rest
        if len(str(nr)) >= width and nr != first and abs(nr - first) <= GROUP_MAX_SPAN
    ]
    if len(others) != len(rest):
        # One short or far-off part makes the whole tail something other
        # than a list of samples (`48211_2`, `48211_20240115`).
        return (first,)
    if len(others) == 1 and "-" in chain and others[0] > first:
        return tuple(range(first, others[0] + 1))
    return tuple(dict.fromkeys([first, *others]))


def _abbreviated_range_end(first: int, suffix: str) -> int | None:
    """`11584` + `"7"` -> 11587: the suffix replaces the last digits of
    `first`. None when the suffix is not shorter than `first`, or the
    result does not lie above it within `GROUP_MAX_SPAN` (`11813-2`)."""
    first_digits = str(first)
    if len(suffix) >= len(first_digits):
        return None
    last = int(first_digits[: -len(suffix)] + suffix)
    return last if 0 < last - first <= GROUP_MAX_SPAN else None


def sample_nr_from_filename(filename: str) -> int | None:
    """The sample number a photo file name starts with, or None."""
    numbers = sample_nrs_from_filename(filename)
    return numbers[0] if numbers else None


def is_group_photo(relative_path: str) -> bool:
    return len(sample_nrs_from_filename(PurePosixPath(relative_path).name)) > 1


def _natural_key(relative_path: str) -> tuple[Any, ...]:
    """Sort `48211.jpg, 48211b.jpg, 48211_2.jpg, 48211_10.jpg` the way a
    person would: the bare number first, digit runs compared as numbers."""
    name = PurePosixPath(relative_path).name
    stem = name.rsplit(".", 1)[0].lower()
    parts = re.split(r"(\d+)", stem)
    key = tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part != "")
    # A sample's own photos come before the group photos it appears in.
    return (is_group_photo(relative_path), key, relative_path.lower())


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


# --- Settings ---------------------------------------------------------------


class SamplePhotoSettingsStore:
    """Setup section `sample_photos`: `{"folder": "<absolute path>"}`."""

    section_key = SETUP_SECTION_SAMPLE_PHOTOS

    def __init__(self, setup_store: SetupStore) -> None:
        self._store = setup_store

    def load(self) -> dict[str, str]:
        raw = self._store.get_section(self.section_key, default={})
        folder = raw.get("folder") if isinstance(raw, dict) else ""
        return {"folder": folder.strip() if isinstance(folder, str) else ""}

    def folder(self) -> Path | None:
        folder = self.load()["folder"]
        return Path(folder) if folder else None

    def update(self, payload: dict[str, Any]) -> dict[str, str]:
        folder = str(payload.get("folder") or "").strip().strip('"')
        # Blank is allowed and switches the feature off. A relative path
        # is refused: it would resolve against whatever directory the
        # service happened to start in.
        if folder and not Path(folder).is_absolute():
            raise ValueError(
                "Enter the full path of the photo folder, e.g. "
                r"\\server\share\SAMS Images or /Volumes/share/SAMS Images."
            )
        cleaned = {"folder": folder}
        self._store.set_section(self.section_key, cleaned)
        return cleaned


# --- Index ------------------------------------------------------------------


@dataclass(frozen=True)
class _Index:
    root: Path
    #: sample_nr -> relative POSIX paths below `root`, naturally sorted.
    files: dict[int, tuple[str, ...]]
    built_at: float
    built_wall: datetime
    error: str | None = None

    @property
    def photo_count(self) -> int:
        # Distinct files: a group photo is listed under several samples.
        return len({path for paths in self.files.values() for path in paths})


@dataclass
class _Scan:
    root: Path
    started_at: float
    done: threading.Event = field(default_factory=threading.Event)


def scan_photo_folder(root: Path) -> dict[int, tuple[str, ...]]:
    """Walk `root` (sub-folders included) and group photo files by the
    sample number(s) their name starts with; a group photo is listed under
    each of its samples. Raises `OSError` when the folder cannot be read."""
    if not root.is_dir():
        raise FileNotFoundError(f"Folder not found: {root}")
    found: dict[int, list[str]] = {}
    # os.walk swallows errors below the top level by default, which is
    # what we want: one unreadable sub-folder must not hide every photo.
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for filename in filenames:
            sample_nrs = sample_nrs_from_filename(filename)
            if not sample_nrs:
                continue
            relative = Path(dirpath, filename).relative_to(root).as_posix()
            for sample_nr in sample_nrs:
                found.setdefault(sample_nr, []).append(relative)
    return {nr: tuple(sorted(paths, key=_natural_key)) for nr, paths in found.items()}


class SamplePhotoLibrary:
    """Process-wide cache of the photo folder listing.

    One index at a time (the configured folder). `ttl_seconds` bounds how
    stale it may get before a lookup triggers a rescan; a stale index keeps
    being served while the rescan runs, so browsing from sample to sample
    never stalls. The operator can force a rescan (refresh button) right
    after dropping new photos into the folder.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 120.0,
        wait_seconds: float = 4.0,
        stalled_after_seconds: float = 60.0,
    ) -> None:
        self.ttl_seconds = ttl_seconds
        self.wait_seconds = wait_seconds
        self.stalled_after_seconds = stalled_after_seconds
        self._lock = threading.Lock()
        self._index: _Index | None = None
        self._scan: _Scan | None = None

    def index_for(self, root: Path, *, refresh: bool = False) -> tuple[_Index | None, bool]:
        """Return `(index, scanning)` for `root`.

        `index` is None while the very first scan is still running.
        `scanning` tells the caller a scan has not come back yet — either
        still walking the folder, or stuck on a dead network mount.
        """
        with self._lock:
            index = self._index if self._index is not None and self._index.root == root else None
            fresh = index is not None and (time.monotonic() - index.built_at) < self.ttl_seconds
            if fresh and not refresh:
                return index, False
            scan = self._scan if self._scan is not None and self._scan.root == root else None
            if scan is None:
                scan = _Scan(root=root, started_at=time.monotonic())
                self._scan = scan
                threading.Thread(
                    target=self._run_scan, args=(scan,), name="sample-photo-scan", daemon=True
                ).start()

            stalled = (time.monotonic() - scan.started_at) > self.stalled_after_seconds

        # A scan that has been out for a minute is stuck on a dead mount.
        # The thread cannot be killed — it comes back when the OS gives up
        # on the share — so stop making every request wait for it.
        finished = scan.done.wait(0 if stalled else self.wait_seconds)
        with self._lock:
            index = self._index if self._index is not None and self._index.root == root else None
        return index, not finished

    def scan_is_stalled(self, root: Path) -> bool:
        with self._lock:
            scan = self._scan
            return (
                scan is not None
                and scan.root == root
                and (time.monotonic() - scan.started_at) > self.stalled_after_seconds
            )

    def _run_scan(self, scan: _Scan) -> None:
        error: str | None = None
        files: dict[int, tuple[str, ...]] = {}
        try:
            files = scan_photo_folder(scan.root)
        except OSError as exc:
            error = exc.strerror or str(exc)
            logger.warning("Sample photo folder %s could not be read: %s", scan.root, exc)
        except Exception:  # noqa: BLE001 - a scan thread must never die silently
            error = "Unexpected error while reading the folder."
            logger.exception("Sample photo scan of %s failed", scan.root)
        index = _Index(
            root=scan.root,
            files=files,
            built_at=time.monotonic(),
            built_wall=datetime.now(),
            error=error,
        )
        with self._lock:
            # A scan of a folder that has since been replaced in Setup must
            # not overwrite the index of the new one.
            if self._scan is scan:
                self._index = index
                self._scan = None
        scan.done.set()


# --- Facade used by the routes ----------------------------------------------


@dataclass(frozen=True)
class SamplePhoto:
    sample_nr: int
    #: Path below the photo folder, POSIX separators. This — not a
    #: filesystem path — is what URLs carry.
    relative_path: str
    size: int
    modified: float
    viewable: bool

    @property
    def name(self) -> str:
        return PurePosixPath(self.relative_path).name

    @property
    def url(self) -> str:
        # `v` makes the URL change when the file is replaced, which is what
        # lets the file route hand out a long cache lifetime.
        return (
            f"/samples/{self.sample_nr}/photos/{quote(self.relative_path)}"
            f"?v={int(self.modified)}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.relative_path,
            "url": self.url,
            "download_url": f"{self.url}&download=1",
            "size": self.size,
            "size_label": _format_size(self.size),
            "modified": datetime.fromtimestamp(self.modified).strftime("%Y-%m-%d"),
            "viewable": self.viewable,
            # Shows this sample together with others (`25328-25337.jpg`).
            "group": is_group_photo(self.relative_path),
        }


@dataclass(frozen=True)
class PhotoListing:
    state: str
    photos: tuple[SamplePhoto, ...] = ()
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "message": self.message,
            "photos": [photo.as_dict() for photo in self.photos],
        }


class SamplePhotos:
    def __init__(self, settings: SamplePhotoSettingsStore, library: SamplePhotoLibrary) -> None:
        self._settings = settings
        self._library = library

    def list_for_sample(self, sample_nr: int, *, refresh: bool = False) -> PhotoListing:
        root = self._settings.folder()
        if root is None:
            return PhotoListing(
                STATE_NOT_CONFIGURED, message="No photo folder is configured yet."
            )
        index, scanning = self._library.index_for(root, refresh=refresh)
        if index is None:
            return self._pending_listing(root)
        if index.error is not None:
            return PhotoListing(
                STATE_UNAVAILABLE,
                message=f"The photo folder could not be read ({index.error}).",
            )
        photos: list[SamplePhoto] = []
        for relative_path in index.files.get(sample_nr, ()):
            try:
                stat = (root / relative_path).stat()
            except OSError:
                # Deleted or renamed since the scan; the next scan drops it.
                continue
            photos.append(
                SamplePhoto(
                    sample_nr=sample_nr,
                    relative_path=relative_path,
                    size=stat.st_size,
                    modified=stat.st_mtime,
                    viewable=Path(relative_path).suffix.lower() in VIEWABLE_EXTENSIONS,
                )
            )
        message = None
        if scanning and refresh:
            message = "The folder is still being rescanned - this list may be out of date."
        return PhotoListing(STATE_OK, photos=tuple(photos), message=message)

    def resolve(self, sample_nr: int, relative_path: str) -> Path | None:
        """Filesystem path of one photo of `sample_nr`, or None.

        The request never supplies a path that is joined blindly: it must
        equal one of the paths the scan found *for this sample*, so `..`
        tricks and other samples' files cannot be reached.
        """
        root = self._settings.folder()
        if root is None:
            return None
        index, _scanning = self._library.index_for(root)
        if index is None or relative_path not in index.files.get(sample_nr, ()):
            return None
        path = root / relative_path
        return path if path.is_file() else None

    def status(self, *, refresh: bool = False) -> dict[str, Any]:
        """Folder health for the Setup page."""
        root = self._settings.folder()
        if root is None:
            return {"state": STATE_NOT_CONFIGURED, "message": "No photo folder is configured yet."}
        index, scanning = self._library.index_for(root, refresh=refresh)
        # Unlike the sample page, which prefers a slightly stale list over
        # none, the check reports only what a finished scan found.
        if index is None or scanning:
            listing = self._pending_listing(root)
            return {"state": listing.state, "message": listing.message}
        if index.error is not None:
            return {
                "state": STATE_UNAVAILABLE,
                "message": f"The photo folder could not be read ({index.error}).",
            }
        return {
            "state": STATE_OK,
            "message": (
                f"{index.photo_count} photo file(s) for {len(index.files)} sample(s), "
                f"scanned {index.built_wall.strftime('%H:%M:%S')}."
            ),
            "photo_count": index.photo_count,
            "sample_count": len(index.files),
        }

    def _pending_listing(self, root: Path) -> PhotoListing:
        if self._library.scan_is_stalled(root):
            return PhotoListing(
                STATE_UNAVAILABLE,
                message=(
                    "The photo folder is not answering. "
                    "Check that the network drive is connected on the server."
                ),
            )
        return PhotoListing(STATE_SCANNING, message="Reading the photo folder...")


def photo_media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


#: The one library of this process (the server runs a single worker).
_LIBRARY = SamplePhotoLibrary()


def get_photo_library() -> SamplePhotoLibrary:
    return _LIBRARY

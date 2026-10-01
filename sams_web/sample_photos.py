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

from dataclasses import asdict, dataclass, field
from datetime import datetime
import errno
import getpass
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
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


# --- Diagnostics ------------------------------------------------------------


def _on_windows() -> bool:
    return os.name == "nt"


def _is_service_account() -> bool:
    """LocalSystem (and other machine accounts) report `SERVER$`."""
    return _on_windows() and os.environ.get("USERNAME", "").endswith("$")


def _is_elevated() -> bool:
    """Started with "Run as administrator". Windows keeps such a program in
    a separate logon session that does not see the drive letters (or the
    saved share logins) of the user's normal session."""
    if not _on_windows():
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:  # noqa: BLE001 - only used in a message
        return False


def _drive_exists(drive: str) -> bool:
    return os.path.exists(drive + "\\")


def running_as() -> str:
    """The account this process runs as — the one whose rights decide
    whether the photo folder can be read. A Windows service left at its
    default runs as LocalSystem, which reaches the network as the computer
    account (`SERVER$`) and has no mapped drives."""
    if _on_windows():
        user = os.environ.get("USERNAME", "")
        domain = os.environ.get("USERDOMAIN", "")
        account = f"{domain}\\{user}" if domain and user else user or "unknown"
        if _is_service_account():
            account += ", LocalSystem / computer account"
        elif _is_elevated():
            account += ", started as administrator"
        return account
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 - only used in a message
        return "unknown"


def _missing_drive(root: Path | None) -> str | None:
    """`"R:"` when `root` is on a drive letter this process cannot see."""
    if root is None or not _on_windows():
        return None
    drive = PureWindowsPath(str(root)).drive
    if len(drive) == 2 and drive[1] == ":" and not _drive_exists(drive):
        return drive.upper()
    return None


def _session_hint() -> str:
    """Why a share that works in Explorer may not work for webSAMS."""
    if _is_service_account():
        return (
            "webSAMS runs as a Windows service, which never sees mapped drives and "
            "logs in to other computers as the computer account."
        )
    if _is_elevated():
        return (
            "webSAMS was started as administrator: Windows hides the drive letters and "
            "share connections of your normal session from such programs, so it needs a "
            "connection of its own. Start it without 'Run as administrator'."
        )
    return ""


def _server_of(root: Path | None) -> str:
    """`192.168.123.30` for `\\\\192.168.123.30\\KTA\\...`, else a generic name."""
    if root is not None:
        drive = PureWindowsPath(str(root)).drive
        if drive.startswith("\\\\"):
            return drive.lstrip("\\").split("\\", 1)[0]
    return "the file server"


def _capitalized(sentence: str) -> str:
    return sentence[:1].upper() + sentence[1:]


@dataclass(frozen=True)
class FolderProblem:
    """Why the photo folder cannot be read, in three layers: what happened
    (`title`), what to do (`advice`), and the facts an administrator needs
    (`folder`, `account`, `os_error`). The sample page shows all three."""

    title: str
    advice: str
    folder: str
    account: str
    os_error: str = ""

    def as_text(self) -> str:
        detail = f"folder {self.folder}, webSAMS runs as {self.account}"
        if self.os_error:
            detail += f", {self.os_error}"
        return " ".join(part for part in (f"{self.title}.", self.advice) if part) + f" ({detail})"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


#: Windows error codes by what they mean for the operator. They are checked
#: before the exception class: Python reports "network path not found"
#: (53, 67) as FileNotFoundError, which would otherwise read "no such folder".
_WIN_SERVER_FULL = {71}  # ERROR_REQ_NOT_ACCEP: the server's client limit is reached
_WIN_UNREACHABLE = {53, 59, 64, 121, 1203, 1222, 1231, 1232}
_WIN_SHARE_MISSING = {67}
_WIN_OTHER_USER = {1219}
_WIN_ACCESS_REFUSED = {5, 86, 1244, 1272, 1326}
_WIN_NOT_FOUND = {2, 3}
_POSIX_UNREACHABLE = {
    errno.EHOSTDOWN, errno.EHOSTUNREACH, errno.ENETDOWN, errno.ENETUNREACH,
    errno.ETIMEDOUT, errno.ENOTCONN, errno.ESTALE,
}


def diagnose_folder_error(exc: OSError, root: Path | None = None) -> FolderProblem:
    """Turn an OS error on the photo folder into something an operator can act on."""
    winerror = getattr(exc, "winerror", None)
    server = _server_of(root)
    hint = _session_hint()
    raw = exc.strerror or str(exc)
    missing_drive = _missing_drive(root)

    if missing_drive:
        title = f"Drive {missing_drive} is not available to webSAMS"
        advice = hint or (
            "A mapped drive letter only exists for the Windows user who mapped it. "
            "Connect the drive for this account, or enter the network path in "
            "Setup → Sample Photos."
        )
    elif winerror in _WIN_SERVER_FULL:
        title = _capitalized(f"{server} accepts no more connections")
        advice = (
            "Too many computers are connected to it at once (a desktop Windows allows 20). "
            "Try again in a few minutes; if it keeps happening, close idle connections on "
            "the file server."
        )
        if _is_elevated() and not _is_service_account():
            advice += " " + hint
    elif winerror in _WIN_UNREACHABLE or exc.errno in _POSIX_UNREACHABLE:
        title = _capitalized(f"{server} cannot be reached")
        advice = "Check that it is switched on and connected to the network, then try again."
    elif winerror in _WIN_SHARE_MISSING:
        title = f"The shared folder on {server} was not found"
        advice = "Check the share name in Setup → Sample Photos."
    elif winerror in _WIN_OTHER_USER:
        title = f"Windows is already connected to {server} as a different user"
        advice = (
            "Only one user name per server is allowed. Disconnect the other connection "
            "(net use) or use the same user for both."
        )
    elif winerror in _WIN_ACCESS_REFUSED or isinstance(exc, PermissionError):
        title = "Access to the photo folder was refused"
        advice = hint or (
            "The account webSAMS runs as may not read this folder. Give it read access, "
            "or run webSAMS as an account that has it."
        )
    elif winerror in _WIN_NOT_FOUND or isinstance(exc, (FileNotFoundError, NotADirectoryError)):
        title = "The photo folder does not exist"
        advice = hint or "Check the path in Setup → Sample Photos."
    else:
        title = "The photo folder could not be read"
        advice = hint
    return FolderProblem(
        title=title,
        advice=advice,
        folder=str(root) if root is not None else "?",
        account=running_as(),
        os_error=f"WinError {winerror}: {raw}" if winerror else raw,
    )


def describe_folder_error(exc: OSError, root: Path | None = None) -> str:
    """`diagnose_folder_error` as one line, for logs and the Setup check."""
    return diagnose_folder_error(exc, root).as_text()


def _stalled_problem(root: Path) -> FolderProblem:
    return FolderProblem(
        title=_capitalized(f"{_server_of(root)} is not answering"),
        advice=(
            "webSAMS has been waiting more than a minute for the photo folder. Check that "
            "the file server and the network are up, then try again."
        ),
        folder=str(root),
        account=running_as(),
    )


# --- Index ------------------------------------------------------------------


@dataclass(frozen=True)
class _Index:
    root: Path
    #: sample_nr -> relative POSIX paths below `root`, naturally sorted.
    files: dict[int, tuple[str, ...]]
    built_at: float
    built_wall: datetime
    problem: FolderProblem | None = None
    #: Sub-folders that could not be listed, as "name: reason".
    unreadable: tuple[str, ...] = ()

    @property
    def photo_count(self) -> int:
        # Distinct files: a group photo is listed under several samples.
        return len({path for paths in self.files.values() for path in paths})


@dataclass
class _Scan:
    root: Path
    started_at: float
    done: threading.Event = field(default_factory=threading.Event)


def scan_photo_folder(
    root: Path, unreadable: list[str] | None = None
) -> dict[int, tuple[str, ...]]:
    """Walk `root` (sub-folders included) and group photo files by the
    sample number(s) their name starts with; a group photo is listed under
    each of its samples.

    Raises `OSError` — with the operating system's own reason — when `root`
    itself cannot be listed. Sub-folders that cannot be listed are skipped
    and, if `unreadable` is given, appended to it as "name: reason".
    """
    # Open the folder rather than asking `Path.is_dir()`: that answers False
    # for "access denied" as well, which once turned a permission problem
    # on the server into a misleading "Folder not found". And os.walk would
    # silently yield nothing for a top folder it cannot list.
    with os.scandir(root) as entries:
        next(entries, None)

    def note_unreadable(exc: OSError) -> None:
        if unreadable is not None:
            name = Path(exc.filename).name if exc.filename else "?"
            unreadable.append(f"{name}: {exc.strerror or exc}")

    found: dict[int, list[str]] = {}
    # One unreadable sub-folder must not hide every other photo.
    for dirpath, dirnames, filenames in os.walk(root, onerror=note_unreadable):
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
        problem: FolderProblem | None = None
        files: dict[int, tuple[str, ...]] = {}
        unreadable: list[str] = []
        try:
            files = scan_photo_folder(scan.root, unreadable)
        except OSError as exc:
            problem = diagnose_folder_error(exc, scan.root)
            logger.warning("Sample photo folder %s could not be read: %s", scan.root, problem.as_text())
        except Exception:  # noqa: BLE001 - a scan thread must never die silently
            problem = FolderProblem(
                title="The photo folder could not be read",
                advice="An unexpected error occurred; see the webSAMS log.",
                folder=str(scan.root),
                account=running_as(),
            )
            logger.exception("Sample photo scan of %s failed", scan.root)
        index = _Index(
            root=scan.root,
            files=files,
            built_at=time.monotonic(),
            built_wall=datetime.now(),
            problem=problem,
            unreadable=tuple(unreadable),
        )
        if unreadable:
            logger.warning(
                "Sample photo scan of %s skipped %d sub-folder(s): %s",
                scan.root, len(unreadable), "; ".join(unreadable[:5]),
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
    #: Set when `state` is unavailable: why, and what to do about it.
    problem: FolderProblem | None = None

    @classmethod
    def unavailable(cls, problem: FolderProblem) -> "PhotoListing":
        return cls(STATE_UNAVAILABLE, message=problem.as_text(), problem=problem)

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "message": self.message,
            "problem": self.problem.as_dict() if self.problem else None,
            "photos": [photo.as_dict() for photo in self.photos],
        }


def _is_plain_missing(exc: OSError) -> bool:
    """A file that is simply gone — not a share that stopped answering,
    which Windows *also* reports as FileNotFoundError (53, 67)."""
    return isinstance(exc, FileNotFoundError) and getattr(exc, "winerror", None) in (None, 2, 3)


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
        if index.problem is not None:
            return PhotoListing.unavailable(index.problem)
        photos: list[SamplePhoto] = []
        missing = 0
        for relative_path in index.files.get(sample_nr, ()):
            try:
                stat = (root / relative_path).stat()
            except OSError as exc:
                if not _is_plain_missing(exc):
                    # The share went away after the last good scan: say so,
                    # rather than presenting the sample as having no photos.
                    return PhotoListing.unavailable(diagnose_folder_error(exc, root))
                # Deleted or renamed since the scan; the next scan drops it.
                missing += 1
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
        if missing and not photos:
            # Every listed photo is gone: a vanished mount looks exactly like
            # that on some systems, so check the folder itself once.
            try:
                with os.scandir(root) as entries:
                    next(entries, None)
            except OSError as exc:
                return PhotoListing.unavailable(diagnose_folder_error(exc, root))
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
        if index.problem is not None:
            return {"state": STATE_UNAVAILABLE, "message": index.problem.as_text()}
        message = (
            f"{index.photo_count} photo file(s) for {len(index.files)} sample(s), "
            f"scanned {index.built_wall.strftime('%H:%M:%S')} as {running_as()}."
        )
        if index.unreadable:
            shown = "; ".join(index.unreadable[:3])
            more = f" and {len(index.unreadable) - 3} more" if len(index.unreadable) > 3 else ""
            message += f" {len(index.unreadable)} sub-folder(s) could not be read ({shown}{more})."
        if index.photo_count == 0:
            message += " No file name starts with a sample number - is this the right folder?"
        return {
            "state": STATE_OK,
            "message": message,
            "photo_count": index.photo_count,
            "sample_count": len(index.files),
        }

    def _pending_listing(self, root: Path) -> PhotoListing:
        if self._library.scan_is_stalled(root):
            return PhotoListing.unavailable(_stalled_problem(root))
        return PhotoListing(STATE_SCANNING, message="Reading the photo folder...")


def photo_media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


#: The one library of this process (the server runs a single worker).
_LIBRARY = SamplePhotoLibrary()


def get_photo_library() -> SamplePhotoLibrary:
    return _LIBRARY

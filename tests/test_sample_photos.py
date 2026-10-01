from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sams_web.dependencies import get_sample_photos
from sams_web.main import app
from sams_web.sample_photos import (
    STATE_NOT_CONFIGURED,
    STATE_OK,
    STATE_SCANNING,
    STATE_UNAVAILABLE,
    SamplePhotoLibrary,
    SamplePhotoSettingsStore,
    SamplePhotos,
    describe_folder_error,
    running_as,
    sample_nr_from_filename,
    sample_nrs_from_filename,
    scan_photo_folder,
)
from sams_web.setup_store import SetupStore


def _touch(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"\xff\xd8 not really a jpeg")


def _photos(tmp_path: Path, folder: Path | None, **library_kwargs) -> SamplePhotos:
    store = SetupStore(tmp_path / "setup_data.json", seed_path=None)
    settings = SamplePhotoSettingsStore(store)
    if folder is not None:
        settings.update({"folder": str(folder)})
    return SamplePhotos(settings, SamplePhotoLibrary(**library_kwargs))


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("48211.jpg", 48211),
        ("48211b.JPG", 48211),
        ("48211_2.jpeg", 48211),
        ("48211 (1).png", 48211),
        ("48211-back.tif", 48211),
        ("00482.jpg", 482),
        ("482110.jpg", 482110),  # a different sample, not a photo of 48211
        ("MAMS-48211.jpg", None),
        ("._48211.jpg", None),  # macOS resource fork
        ("48211.txt", None),
        ("48211", None),
        ("Thumbs.db", None),
    ],
)
def test_sample_number_is_read_from_the_start_of_the_file_name(filename, expected):
    assert sample_nr_from_filename(filename) == expected


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        # Numbers written out in full: a dash pair is a range, the rest lists.
        ("25328-25331.jpg", (25328, 25329, 25330, 25331)),
        ("9998-10001.jpg", (9998, 9999, 10000, 10001)),
        ("16191_16192.JPG", (16191, 16192)),
        ("16881+16882b.JPG", (16881, 16882)),
        ("12419-12420-12423-12425.JPG", (12419, 12420, 12423, 12425)),
        # A short number after a dash replaces the last digits.
        ("11584-7.JPG", (11584, 11585, 11586, 11587)),
        ("14518-20.JPG", (14518, 14519, 14520)),
        ("22033-5a.jpg", (22033, 22034, 22035)),
        # ...unless that would end below the start: then it is a counter.
        ("11813-2.JPG", (11813,)),
        # Underscores never abbreviate; a short number is a photo counter.
        ("36231_2.JPG", (36231,)),
        ("44648_651_652.jpg", (44648,)),
        # Numeric, but not a neighbouring sample.
        ("48211_20240115.jpg", (48211,)),
        ("48211-48990.jpg", (48211,)),
        # Not chained directly onto the first number.
        ("12875_beschriftet12876.JPG", (12875,)),
    ],
)
def test_group_photos_name_every_sample_in_full(filename, expected):
    assert sample_nrs_from_filename(filename) == expected


def test_a_group_photo_is_listed_on_each_sample_after_its_own_photos(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "100-102.jpg", "101.jpg", "101b.jpg", "102_103.jpg")
    photos = _photos(tmp_path, folder)

    listing = photos.list_for_sample(101)
    assert [photo.name for photo in listing.photos] == ["101.jpg", "101b.jpg", "100-102.jpg"]
    assert [photo["group"] for photo in listing.as_dict()["photos"]] == [False, False, True]
    assert [photo.name for photo in photos.list_for_sample(102).photos] == ["100-102.jpg", "102_103.jpg"]
    assert [photo.name for photo in photos.list_for_sample(103).photos] == ["102_103.jpg"]

    # Served under every sample it shows, and only those.
    assert photos.resolve(100, "100-102.jpg") == folder / "100-102.jpg"
    assert photos.resolve(102, "100-102.jpg") == folder / "100-102.jpg"
    assert photos.resolve(103, "100-102.jpg") is None
    # Four files, however many samples they are listed under.
    assert photos.status()["photo_count"] == 4


def test_scan_groups_files_by_sample_and_descends_into_subfolders(tmp_path):
    folder = tmp_path / "SAMS Images"
    _touch(
        folder,
        "100.jpg",
        "100_10.jpg",
        "100_2.jpg",
        "100b.jpg",
        "1000.jpg",
        "2024/101.png",
        ".hidden/100z.jpg",
        "notes.txt",
    )

    found = scan_photo_folder(folder)

    # The legacy `100*.jpg` glob would also have returned 1000.jpg here.
    assert found[100] == ("100.jpg", "100_2.jpg", "100_10.jpg", "100b.jpg")
    assert found[1000] == ("1000.jpg",)
    assert found[101] == ("2024/101.png",)
    assert set(found) == {100, 101, 1000}


def test_listing_reports_each_state(tmp_path):
    assert _photos(tmp_path, None).list_for_sample(1).state == STATE_NOT_CONFIGURED

    missing = _photos(tmp_path, tmp_path / "gone").list_for_sample(1)
    assert missing.state == STATE_UNAVAILABLE

    folder = tmp_path / "photos"
    _touch(folder, "7.jpg", "7b.tif", "8.jpg")
    listing = _photos(tmp_path, folder).list_for_sample(7)
    assert listing.state == STATE_OK
    assert [photo.name for photo in listing.photos] == ["7.jpg", "7b.tif"]
    assert [photo.viewable for photo in listing.photos] == [True, False]
    assert listing.as_dict()["photos"][0]["download_url"].endswith("&download=1")

    assert _photos(tmp_path, folder).list_for_sample(9).photos == ()


def test_refresh_picks_up_a_photo_added_after_the_first_scan(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "7.jpg")
    photos = _photos(tmp_path, folder)
    assert len(photos.list_for_sample(7).photos) == 1

    _touch(folder, "7b.jpg")
    assert len(photos.list_for_sample(7).photos) == 1  # index is still fresh
    assert len(photos.list_for_sample(7, refresh=True).photos) == 2


def test_a_slow_folder_answers_scanning_instead_of_blocking(tmp_path, monkeypatch):
    import threading

    import sams_web.sample_photos as module

    release = threading.Event()

    def slow_scan(_root, _unreadable=None):
        release.wait(5)
        return {7: ("7.jpg",)}

    monkeypatch.setattr(module, "scan_photo_folder", slow_scan)
    folder = tmp_path / "photos"
    _touch(folder, "7.jpg")
    photos = _photos(tmp_path, folder, wait_seconds=0.05)

    assert photos.list_for_sample(7).state == STATE_SCANNING
    release.set()
    # The scan finishes in the background; the next request sees its result.
    for _ in range(100):
        listing = photos.list_for_sample(7)
        if listing.state == STATE_OK:
            break
    assert [photo.name for photo in listing.photos] == ["7.jpg"]


def test_resolve_only_returns_files_found_for_that_sample(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "7.jpg", "sub/7b.jpg", "8.jpg")
    (tmp_path / "secret.jpg").write_bytes(b"x")
    photos = _photos(tmp_path, folder)

    assert photos.resolve(7, "7.jpg") == folder / "7.jpg"
    assert photos.resolve(7, "sub/7b.jpg") == folder / "sub" / "7b.jpg"
    assert photos.resolve(7, "8.jpg") is None  # another sample's photo
    assert photos.resolve(7, "../secret.jpg") is None
    assert photos.resolve(7, str(tmp_path / "secret.jpg")) is None


def test_settings_reject_a_relative_folder_and_accept_blank(tmp_path):
    settings = SamplePhotoSettingsStore(SetupStore(tmp_path / "setup_data.json", seed_path=None))
    with pytest.raises(ValueError):
        settings.update({"folder": "SAMS Images"})
    assert settings.update({"folder": "  "}) == {"folder": ""}
    assert settings.folder() is None


@pytest.fixture
def client(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "7.jpg", "7 b.jpg", "8.jpg")
    app.dependency_overrides[get_sample_photos] = lambda: _photos(tmp_path, folder)
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_sample_photos, None)


def test_routes_list_serve_and_download_photos(client):
    listing = client.get("/api/samples/7/photos").json()
    assert listing["state"] == STATE_OK
    assert [photo["name"] for photo in listing["photos"]] == ["7.jpg", "7 b.jpg"]

    spaced = listing["photos"][1]
    assert "7%20b.jpg" in spaced["url"]

    inline = client.get(spaced["url"])
    assert inline.status_code == 200
    assert inline.headers["content-type"] == "image/jpeg"
    assert inline.headers["content-disposition"].startswith("inline")
    assert inline.content.startswith(b"\xff\xd8")

    download = client.get(spaced["download_url"])
    assert download.headers["content-disposition"].startswith("attachment")

    assert client.get("/samples/7/photos/8.jpg").status_code == 404
    assert client.get("/samples/7/photos/..%2F..%2Fsetup_data.json").status_code == 404


def test_an_unreadable_folder_says_access_denied_and_names_the_account(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "7.jpg")
    folder.chmod(0)
    try:
        listing = _photos(tmp_path, folder).list_for_sample(7)
    finally:
        folder.chmod(0o755)
    assert listing.state == STATE_UNAVAILABLE
    # Not "Folder not found": that is what Path.is_dir() used to make of it.
    assert "Access denied" in listing.message
    assert running_as() in listing.message


def test_a_missing_folder_says_not_found(tmp_path):
    listing = _photos(tmp_path, tmp_path / "gone").list_for_sample(7)
    assert "Folder not found" in listing.message


@pytest.mark.parametrize(
    ("winerror", "expected"),
    [(53, "Folder not found"), (67, "Folder not found"), (1326, "Access denied"), (5, "Access denied")],
)
def test_windows_share_errors_are_named(winerror, expected):
    exc = OSError(0, "Windows says no")
    exc.winerror = winerror  # only set by Python itself on Windows
    message = describe_folder_error(exc)
    assert message.startswith(expected)
    assert f"[WinError {winerror}: Windows says no]" in message


def test_an_unreadable_sub_folder_is_skipped_and_reported(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "1-100/7.jpg", "101-200/150.jpg")
    (folder / "101-200").chmod(0)
    try:
        photos = _photos(tmp_path, folder)
        assert [photo.name for photo in photos.list_for_sample(7).photos] == ["7.jpg"]
        status = photos.status()
    finally:
        (folder / "101-200").chmod(0o755)
    assert status["state"] == STATE_OK
    assert "1 sub-folder(s) could not be read (101-200:" in status["message"]


class _FakeWindows:
    """Just enough of a Windows process for the diagnostics."""

    def __init__(self, monkeypatch, *, user, elevated=False, drives=("C:",)):
        import sams_web.sample_photos as module

        monkeypatch.setattr(module, "_on_windows", lambda: True)
        monkeypatch.setattr(module, "_is_elevated", lambda: elevated)
        monkeypatch.setattr(module, "_drive_exists", lambda drive: drive.upper() in drives)
        monkeypatch.setenv("USERNAME", user)
        monkeypatch.setenv("USERDOMAIN", "LAB")


def _not_found(winerror=3):
    exc = OSError(0, "The system cannot find the path specified")
    exc.winerror = winerror
    return exc


def test_a_service_is_told_it_cannot_see_mapped_drives(monkeypatch):
    _FakeWindows(monkeypatch, user="WEBSAMS-SRV$")
    message = describe_folder_error(_not_found(), Path("R:/SAMS Images"))
    assert message.startswith("Drive R: does not exist for webSAMS (LAB\\WEBSAMS-SRV$, LocalSystem")
    assert "Windows service" in message


def test_an_elevated_start_is_named_as_the_reason(monkeypatch):
    _FakeWindows(monkeypatch, user="rfriedrich", elevated=True)
    message = describe_folder_error(_not_found(), Path("R:/SAMS Images"))
    assert "started as administrator" in message
    assert "without 'Run as administrator'" in message

    denied = OSError(0, "The user name or password is incorrect")
    denied.winerror = 1326
    message = describe_folder_error(denied, Path("//192.168.123.30/KTA/SAMS Images"))
    assert message.startswith("Access denied")
    assert "without 'Run as administrator'" in message


def test_an_existing_drive_with_a_wrong_folder_is_a_plain_not_found(monkeypatch):
    _FakeWindows(monkeypatch, user="rfriedrich", drives=("C:", "R:"))
    message = describe_folder_error(_not_found(), Path("R:/SAMS Imgs"))
    assert message.startswith("Folder not found for the account webSAMS runs as (LAB\\rfriedrich)")
    assert "check the path" in message

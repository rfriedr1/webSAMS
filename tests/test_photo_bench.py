"""Photo bench: writing new photos into the photo folder, and its routes."""

from __future__ import annotations

from pathlib import Path
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from sams_web.dependencies import get_sample_photos, get_service
from sams_web.main import app
from sams_web.photo_bench import is_jpeg, parse_sample_nr, sample_nr_from_label
from sams_web.sample_photos import (
    PhotoSaveError,
    SamplePhotoLibrary,
    SamplePhotoSettingsStore,
    SamplePhotos,
    next_photo_name,
    photo_target_folder,
    sample_nrs_from_filename,
    write_new_photos,
)
from sams_web.setup_store import SetupStore

JPEG = b"\xff\xd8\xff\xe0 fake jpeg body"


def _touch(folder: Path, *names: str) -> None:
    for name in names:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(JPEG)


def _photos(tmp_path: Path, folder: Path | None, **library_kwargs) -> SamplePhotos:
    store = SetupStore(tmp_path / "setup_data.json", seed_path=None)
    settings = SamplePhotoSettingsStore(store)
    if folder is not None:
        settings.update({"folder": str(folder)})
    return SamplePhotos(settings, SamplePhotoLibrary(**library_kwargs))


# ---- label text -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("48211", 48211),
        (" 048211 \n", 48211),
        ("MAMS-48211", 48211),
        ("mams 48211", 48211),
        ("MAMS:048211", 48211),
        ("Sample 48211", 48211),
        ("48211 / 48212", None),  # two numbers: not guessed at
        ("R-EVA 12", None),  # too short to be a sample number
        ("", None),
        (None, None),
        ("0", None),
    ],
)
def test_sample_nr_from_label(text, expected):
    assert sample_nr_from_label(text) == expected


def test_parse_sample_nr_and_jpeg_check():
    assert parse_sample_nr(" 48211 ") == 48211
    assert parse_sample_nr("48211a") is None
    assert parse_sample_nr("0") is None
    assert is_jpeg(JPEG)
    assert not is_jpeg(b"\x89PNG\r\n")


def test_js_label_rule_mirrors_python():
    """photo-bench.js carries a copy of the rule (`labelSampleNr`)."""
    script = (Path(__file__).parent.parent / "sams_web/static/js/photo-bench.js").read_text()
    assert r"/MAMS[\s:_-]*0*(\d{1,7})\b/i" in script
    assert "run.length >= 3" in script


# ---- range folder and names ----------------------------------------------


def test_target_folder_uses_existing_range_folders(tmp_path):
    for name in ("1-10000", "10001-15000", "90001-95000", "new", "other"):
        (tmp_path / name).mkdir()
    assert photo_target_folder(tmp_path, 482) == "1-10000"
    assert photo_target_folder(tmp_path, 10001) == "10001-15000"
    assert photo_target_folder(tmp_path, 92345) == "90001-95000"


def test_target_folder_creates_the_next_range(tmp_path):
    (tmp_path / "90001-95000").mkdir()
    (tmp_path / "95001-100000.jpg").write_bytes(JPEG)  # a file, not a folder
    assert photo_target_folder(tmp_path, 96000) == "95001-100000"
    assert (tmp_path / "95001-100000").is_dir()
    assert photo_target_folder(tmp_path, 100001) == "100001-105000"
    assert (tmp_path / "100001-105000").is_dir()


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        ((), "48211.jpg"),
        (("40001-50000/48211.jpg",), "48211_2.jpg"),
        (("a/48211b.jpg",), "48211_2.jpg"),
        (("a/48211.jpg", "a/48211_2.jpg", "b/48211_3.png"), "48211_4.jpg"),
        (("a/48211.jpg", "a/48211_3.jpg"), "48211_2.jpg"),
        # A group photo is not one of the sample's own.
        (("a/48210-48215.jpg",), "48211.jpg"),
    ],
)
def test_next_photo_name(existing, expected):
    assert next_photo_name(48211, existing) == expected


@pytest.mark.parametrize("name", ["48211.jpg", "48211_2.jpg", "48211_10.jpg", "48211_99.jpg"])
def test_new_names_belong_to_that_sample_only(name):
    assert sample_nrs_from_filename(name) == (48211,)


def test_write_never_overwrites(tmp_path):
    _touch(tmp_path, "45001-50000/48211.jpg", "45001-50000/48211_2.jpg")
    # The index knows neither file: the exclusive create finds them.
    written = write_new_photos(tmp_path, 48211, (), [b"\xff\xd8\xff one", b"\xff\xd8\xff two"])
    assert written == ["45001-50000/48211_3.jpg", "45001-50000/48211_4.jpg"]
    assert (tmp_path / "45001-50000/48211.jpg").read_bytes() == JPEG
    assert (tmp_path / "45001-50000/48211_2.jpg").read_bytes() == JPEG


def test_write_skips_a_name_taken_in_the_target_folder(tmp_path):
    _touch(tmp_path, "45001-50000/48211.jpg")
    written = write_new_photos(tmp_path, 48211, (), [b"\xff\xd8\xff new"])
    assert written == ["45001-50000/48211_2.jpg"]
    assert (tmp_path / "45001-50000/48211.jpg").read_bytes() == JPEG
    assert (tmp_path / "45001-50000/48211_2.jpg").read_bytes() == b"\xff\xd8\xff new"


# ---- SamplePhotos.save_new -------------------------------------------------


def test_save_new_names_files_and_updates_the_index_at_once(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "45001-50000/48211.jpg", "45001-50000/48212.jpg")
    photos = _photos(tmp_path, folder)
    assert [p.name for p in photos.list_for_sample(48211).photos] == ["48211.jpg"]

    saved = photos.save_new(48211, [b"\xff\xd8\xff a", b"\xff\xd8\xff b"])

    assert [p.relative_path for p in saved] == ["45001-50000/48211_2.jpg", "45001-50000/48211_3.jpg"]
    # No rescan needed: listing and resolve see the new files.
    listing = photos.list_for_sample(48211)
    assert [p.name for p in listing.photos] == ["48211.jpg", "48211_2.jpg", "48211_3.jpg"]
    assert photos.resolve(48211, "45001-50000/48211_3.jpg") == folder / "45001-50000/48211_3.jpg"


def test_save_new_first_photo_of_a_new_sample_gets_the_bare_number(tmp_path):
    folder = tmp_path / "photos"
    (folder / "90001-95000").mkdir(parents=True)
    photos = _photos(tmp_path, folder)
    saved = photos.save_new(96123, [JPEG])
    assert [p.relative_path for p in saved] == ["95001-100000/96123.jpg"]


def test_save_new_refuses_without_folder(tmp_path):
    with pytest.raises(PhotoSaveError) as caught:
        _photos(tmp_path, None).save_new(48211, [JPEG])
    assert "Setup" in caught.value.message


def test_save_new_reports_an_unreadable_folder(tmp_path):
    photos = _photos(tmp_path, tmp_path / "missing")
    with pytest.raises(PhotoSaveError) as caught:
        photos.save_new(48211, [JPEG])
    assert caught.value.problem is not None
    assert caught.value.problem.title == "The photo folder does not exist"


def test_save_new_gives_up_on_a_folder_that_does_not_answer(tmp_path, monkeypatch):
    folder = tmp_path / "photos"
    folder.mkdir()
    photos = _photos(tmp_path, folder)
    photos.write_timeout_seconds = 0.2
    release = threading.Event()
    monkeypatch.setattr(
        "sams_web.sample_photos.write_new_photos",
        lambda *args, **kwargs: release.wait(5) or [],
    )
    try:
        with pytest.raises(PhotoSaveError) as caught:
            photos.save_new(48211, [JPEG])
        assert "not answering" in caught.value.problem.title
    finally:
        release.set()


def test_files_added_during_a_scan_survive_it(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "1-10000/7.jpg")
    library = SamplePhotoLibrary()
    library.index_for(folder)
    started = threading.Event()
    proceed = threading.Event()

    import sams_web.sample_photos as module

    real_scan = module.scan_photo_folder

    def slow_scan(root, unreadable=None):
        found = real_scan(root, unreadable)  # walks before the new file exists
        started.set()
        proceed.wait(5)
        return found

    module_scan = "sams_web.sample_photos.scan_photo_folder"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(module_scan, slow_scan)
        library.index_for(folder, refresh=True)  # starts the slow rescan
        assert started.wait(5)
        _touch(folder, "1-10000/7_2.jpg")
        library.add_files(folder, ["1-10000/7_2.jpg"])
        proceed.set()
        for _ in range(50):
            index, scanning = library.index_for(folder)
            if not scanning:
                break
    assert index.files[7] == ("1-10000/7.jpg", "1-10000/7_2.jpg")


# ---- route -------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    folder = tmp_path / "photos"
    _touch(folder, "1-10000/7.jpg")
    photos = _photos(tmp_path, folder)
    fake_service = SimpleNamespace(sample_exists=lambda nr: nr in (7, 8))
    app.dependency_overrides[get_sample_photos] = lambda: photos
    app.dependency_overrides[get_service] = lambda: fake_service
    try:
        yield TestClient(app), folder
    finally:
        app.dependency_overrides.pop(get_sample_photos, None)
        app.dependency_overrides.pop(get_service, None)


def _files(*items):
    return [("files", (name, data, "image/jpeg")) for name, data in items]


def test_route_saves_jpegs(client):
    http, folder = client
    response = http.post("/samples/7/photos", files=_files(("shot.jpg", JPEG), ("b.jpg", JPEG)))
    assert response.status_code == 200
    body = response.json()
    assert [photo["name"] for photo in body["saved"]] == ["7_2.jpg", "7_3.jpg"]
    assert [photo["name"] for photo in body["listing"]["photos"]] == ["7.jpg", "7_2.jpg", "7_3.jpg"]
    assert (folder / "1-10000/7_3.jpg").read_bytes() == JPEG
    # Served like every other photo.
    assert http.get(body["saved"][0]["url"]).content == JPEG


@pytest.mark.parametrize(
    ("path", "files", "status"),
    [
        ("/samples/9/photos", _files(("a.jpg", JPEG)), 404),
        ("/samples/7/photos", _files(("a.png", b"\x89PNG\r\n\x1a\n")), 415),
        ("/samples/7/photos", _files(*[(f"{n}.jpg", JPEG) for n in range(11)]), 400),
        ("/samples/7/photos", [], 400),
    ],
)
def test_route_refuses(client, path, files, status):
    http, folder = client
    response = http.post(path, files=files) if files else http.post(path, data={"x": "1"})
    assert response.status_code == status
    assert response.json()["error"]
    assert sorted(p.name for p in folder.rglob("*.jpg")) == ["7.jpg"]


def test_route_refuses_an_oversized_photo(client, monkeypatch):
    http, _folder = client
    monkeypatch.setattr("sams_web.routers.pages_photo_bench.MAX_PHOTO_BYTES", 10)
    response = http.post("/samples/7/photos", files=_files(("big.jpg", JPEG)))
    assert response.status_code == 413

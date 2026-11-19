"""Photo bench routes (Samples → Photos).

Registered before the sample routes so the literal `/samples/photos`
is not captured by `/samples/{sample_nr}`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import JSONResponse

from sams_web.access import Permission, guarded
from sams_web.dependencies import get_sample_photos, get_service
from sams_web.photo_bench import (
    MAX_PHOTO_BYTES,
    MAX_PHOTOS_PER_SAVE,
    PhotoBench,
    is_jpeg,
)
from sams_web.routers.pages_shared import templates
from sams_web.sample_photos import PhotoSaveError, SamplePhotos
from sams_web.services import SamsService

router = APIRouter()


@router.get("/samples/photos")
def photo_bench_page(
    request: Request,
    sample_nr: str | None = Query(default=None),
    service: SamsService = Depends(get_service),
):
    context = PhotoBench(service).page_view(sample_nr_raw=sample_nr)
    return templates.TemplateResponse(request, "photo_bench.html", context)


@router.get("/samples/photos/facts")
def photo_bench_facts(
    request: Request,
    sample_nr: str | None = Query(default=None),
    label: str | None = Query(default=None),
    service: SamsService = Depends(get_service),
):
    """The facts line for one sample, as an HTML fragment: the bench swaps
    it in when the sample changes (the camera keeps running), and the
    suggestion card shows it for a label read from a shot. Always 200;
    the fragment carries `data-photo-facts-sample` (empty when unknown)."""
    context = PhotoBench(service).facts_view(sample_nr_raw=sample_nr, label=label)
    return templates.TemplateResponse(request, "_photo_bench_facts.html", context)


def _refused(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": message, "problem": None}, status_code=status)


@router.post("/samples/{sample_nr}/photos", dependencies=guarded(Permission.EDIT_RECORDS))
def save_sample_photos(
    sample_nr: int,
    files: list[UploadFile] = File(default=[]),
    service: SamsService = Depends(get_service),
    photos: SamplePhotos = Depends(get_sample_photos),
):
    """Save the shots of the photo bench as new photos of `sample_nr`.

    JPEG only (checked by content, not by the declared type); file names
    and the range folder are chosen by `SamplePhotos.save_new`. Answers
    JSON: `{saved, listing}` or `{error, problem}`.
    """
    if not service.sample_exists(sample_nr):
        return _refused(404, f"There is no sample {sample_nr}.")
    if not files:
        return _refused(400, "No photos were sent.")
    if len(files) > MAX_PHOTOS_PER_SAVE:
        return _refused(400, f"Save at most {MAX_PHOTOS_PER_SAVE} photos at once.")
    images: list[bytes] = []
    for upload in files:
        data = upload.file.read(MAX_PHOTO_BYTES + 1)
        if len(data) > MAX_PHOTO_BYTES:
            return _refused(
                413, f"{upload.filename or 'A photo'} is larger than {MAX_PHOTO_BYTES // (1024 * 1024)} MB."
            )
        if not is_jpeg(data):
            return _refused(
                415, f"{upload.filename or 'A photo'} is not a JPEG picture; only JPEG is saved."
            )
        images.append(data)
    try:
        saved = photos.save_new(sample_nr, images)
    except PhotoSaveError as exc:
        return JSONResponse(
            {"error": exc.message, "problem": exc.problem.as_dict() if exc.problem else None},
            status_code=503,
        )
    return {
        "saved": [photo.as_dict() for photo in saved],
        "listing": photos.list_for_sample(sample_nr).as_dict(),
    }

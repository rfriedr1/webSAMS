"""FastAPI dependency helpers."""

from __future__ import annotations

from fastapi import Depends
from sqlalchemy.orm import Session

from sams_web.config import get_settings
from sams_web.db import get_session
from sams_web.sample_photos import SamplePhotoSettingsStore, SamplePhotos, get_photo_library
from sams_web.setup_store import SetupStore
from sams_web.services import SamsService
from sams_web.thresholds import ThresholdStore


def get_setup_store() -> SetupStore:
    settings = get_settings()
    return SetupStore(settings.setup_data_file)


def get_threshold_store(setup_store: SetupStore = Depends(get_setup_store)) -> ThresholdStore:
    return ThresholdStore(setup_store)


def get_sample_photos(setup_store: SetupStore = Depends(get_setup_store)) -> SamplePhotos:
    return SamplePhotos(SamplePhotoSettingsStore(setup_store), get_photo_library())


def get_service(
    session: Session = Depends(get_session),
    setup_store: SetupStore = Depends(get_setup_store),
    threshold_store: ThresholdStore = Depends(get_threshold_store),
) -> SamsService:
    return SamsService(
        session,
        threshold_store=threshold_store,
        setup_store=setup_store,
    )

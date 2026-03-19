"""Aggregate router for Magic Nav, sample, preparation, and target pages."""

from __future__ import annotations

from fastapi import APIRouter

from sams_web.routers.pages_magic_nav import router as magic_nav_router
from sams_web.routers.pages_preparations import router as preparations_router
from sams_web.routers.pages_samples import router as samples_router
from sams_web.routers.pages_targets import router as targets_router

router = APIRouter()
router.include_router(magic_nav_router)
router.include_router(samples_router)
router.include_router(preparations_router)
router.include_router(targets_router)

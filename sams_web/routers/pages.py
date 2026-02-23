"""Server-rendered HTML pages."""

from __future__ import annotations

from fastapi import APIRouter

from sams_web.routers.pages_dashboard_setup_help import router as dashboard_setup_help_router
from sams_web.routers.pages_magic_samples import router as magic_samples_router
from sams_web.routers.pages_search_lab_import import router as search_lab_import_router
from sams_web.routers.pages_users_projects import router as users_projects_router

router = APIRouter(tags=["pages"])
router.include_router(dashboard_setup_help_router)
router.include_router(users_projects_router)
router.include_router(magic_samples_router)
router.include_router(search_lab_import_router)

"""Navigation metadata and active-state helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Request

MAIN_NAV_ITEMS: tuple[dict[str, Any], ...] = (
    {"key": "dashboard", "module": "dashboard", "label": "Dashboard", "href": "/", "external": False},
    {"key": "samples", "module": "sample_management", "label": "Samples", "href": "/samples", "external": False},
    {"key": "lab", "module": "lab_operations", "label": "Lab", "href": "/lab/preparation", "external": False},
    {"key": "search", "module": "search", "label": "Search", "href": "/search?global=1", "external": False},
    {"key": "setup", "module": "setup", "label": "Setup", "href": "/setup", "external": False},
    {"key": "help", "module": "help", "label": "Help", "href": "/help", "external": False},
    {"key": "api_docs", "module": "api_docs", "label": "API Docs", "href": "/docs", "external": True},
)

SUB_NAV_ITEMS: dict[str, tuple[dict[str, Any], ...]] = {
    "sample_management": (
        {"key": "sample", "label": "Sample", "href": "/samples", "external": False},
        {"key": "projects", "label": "Projects", "href": "/projects", "external": False},
        {"key": "submitters", "label": "Submitters", "href": "/submitters", "external": False},
    ),
    "lab_operations": (
        {"key": "preparation", "label": "Preparation", "href": "/lab/preparation", "external": False},
        {"key": "graphitization", "label": "Graphitization", "href": "/lab/graphitization", "external": False},
        {"key": "analysis", "label": "Analysis", "href": "/lab/analysis", "external": False},
    ),
    # Search / Setup / Help deliberately have NO sub-nav: each previously
    # showed a single chip duplicating the main nav item ("System
    # Settings" under Settings, etc.) — a whole extra header row with
    # zero navigation value. Sub-nav rows only render for modules with
    # 2+ real destinations.
    "api_docs": (
        {"key": "openapi", "label": "OpenAPI", "href": "/docs", "external": True},
        {"key": "redoc", "label": "ReDoc", "href": "/redoc", "external": True},
    ),
}

NAVIGATION_COMMAND_ENTRIES: tuple[dict[str, str], ...] = (
    {"label": "Dashboard", "href": "/"},
    {"label": "Samples: Sample", "href": "/samples"},
    {"label": "Samples: Projects", "href": "/projects"},
    {"label": "Samples: Submitters", "href": "/submitters"},
    {"label": "Lab Operations: Preparation", "href": "/lab/preparation"},
    {"label": "Lab Operations: Graphitization", "href": "/lab/graphitization"},
    {"label": "Lab Operations: Analysis", "href": "/lab/analysis"},
    {"label": "Search: Global", "href": "/search?global=1"},
    {"label": "Setup", "href": "/setup"},
    {"label": "Help", "href": "/help"},
    {"label": "API Docs", "href": "/docs"},
)


def _query_value(query: Mapping[str, Any], key: str) -> str:
    value = query.get(key) if hasattr(query, "get") else None
    return str(value or "").lower()


def resolve_active_module(request: Request) -> str:
    path = request.url.path
    query = request.query_params
    search_context = _query_value(query, "context")
    search_mode = _query_value(query, "mode")
    search_global = _query_value(query, "global")

    if path == "/":
        return "dashboard"
    if path.startswith("/setup"):
        return "setup"
    if path.startswith("/help"):
        return "help"
    if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi"):
        return "api_docs"
    if path.startswith("/search") and search_global == "1":
        return "search"
    if path.startswith("/lab/"):
        return "lab_operations"
    if path.startswith("/search") and search_mode == "analysis":
        return "lab_operations"
    if path.startswith("/search") and search_context in ("preparations", "targets"):
        return "lab_operations"
    if path.startswith("/search") and search_context in ("samples", "projects", "submitters") and search_global != "1":
        return "sample_management"
    if path.startswith("/search"):
        return "search"
    return "sample_management"


def is_subnav_active(request: Request, module: str, item_key: str) -> bool:
    path = request.url.path
    query = request.query_params
    search_context = _query_value(query, "context")
    search_mode = _query_value(query, "mode")
    search_global = _query_value(query, "global")

    if module == "sample_management":
        if item_key == "sample":
            return (
                (path.startswith("/search") and search_context == "samples" and search_global != "1")
                or path.startswith("/samples")
            )
        if item_key == "projects":
            return path.startswith("/projects") or (path.startswith("/search") and search_context == "projects" and search_global != "1")
        if item_key == "submitters":
            return path.startswith("/submitters") or (path.startswith("/search") and search_context == "submitters" and search_global != "1")

    if module == "lab_operations":
        if item_key == "preparation":
            return path.startswith("/lab/preparation") or (path.startswith("/search") and search_context == "preparations")
        if item_key == "graphitization":
            return path.startswith("/lab/graphitization") or (path.startswith("/search") and search_context == "targets" and search_mode != "analysis")
        if item_key == "analysis":
            return path.startswith("/lab/analysis") or (path.startswith("/search") and search_mode == "analysis")

    if module == "search" and item_key == "global_search":
        return path.startswith("/search") and resolve_active_module(request) == "search"

    if module == "setup" and item_key == "system_setup":
        return path.startswith("/setup")

    if module == "help" and item_key == "help_center":
        return path.startswith("/help")

    if module == "api_docs":
        if item_key == "openapi":
            return path.startswith("/docs")
        if item_key == "redoc":
            return path.startswith("/redoc")

    return False

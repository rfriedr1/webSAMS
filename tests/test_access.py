"""The access seam (sams_web/access.py): every write route is guarded."""

from __future__ import annotations

import dataclasses
import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from sams_web import access
from sams_web.access import AppUser, Permission, Role, parse_role
from sams_web.config import get_settings
from sams_web.main import app

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _guard_permissions(route: APIRoute) -> set[Permission]:
    found: set[Permission] = set()
    stack = list(route.dependant.dependencies)
    while stack:
        dependant = stack.pop()
        permission = getattr(dependant.call, "sams_permission", None)
        if permission is not None:
            found.add(permission)
        stack.extend(dependant.dependencies)
    return found


def _write_routes() -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.methods & WRITE_METHODS
    ]


def test_every_write_route_requires_a_permission():
    routes = _write_routes()
    assert len(routes) >= 29
    unguarded = [f"{sorted(r.methods)} {r.path}" for r in routes if not _guard_permissions(r)]
    assert unguarded == [], (
        "Write routes without dependencies=guarded(Permission.X): " + ", ".join(unguarded)
    )


def test_setup_and_signoff_routes_use_their_own_permission():
    by_path = {route.path: _guard_permissions(route) for route in _write_routes()}
    assert by_path["/setup/{section_key}"] == {Permission.MANAGE_SETUP}
    assert by_path["/api/setup/{section_key}"] == {Permission.MANAGE_SETUP}
    assert by_path["/qc/signoffs"] == {Permission.SIGN_OFF_QC}
    assert by_path["/samples/{sample_nr}/save"] == {Permission.EDIT_RECORDS}


def test_roles():
    assert parse_role(None) is Role.ADMIN
    assert parse_role(" Viewer ") is Role.VIEWER
    with pytest.raises(RuntimeError):
        parse_role("superuser")
    viewer = AppUser(None, Role.VIEWER)
    editor = AppUser(None, Role.EDITOR)
    admin = AppUser(None, Role.ADMIN)
    assert not any(viewer.can(p) for p in Permission)
    assert editor.can("edit_records") and not editor.can(Permission.MANAGE_SETUP)
    assert all(admin.can(p) for p in Permission)


@pytest.fixture
def as_viewer(monkeypatch):
    viewer_settings = dataclasses.replace(get_settings(), access_role=Role.VIEWER)
    monkeypatch.setattr(access, "get_settings", lambda: viewer_settings)


def _concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", path)


def test_viewer_gets_403_on_every_write_route(as_viewer):
    client = TestClient(app)
    for route in _write_routes():
        for method in route.methods & WRITE_METHODS:
            response = client.request(method, _concrete(route.path), headers={"accept": "application/json"})
            assert response.status_code == 403, f"{method} {route.path} -> {response.status_code}"


def test_viewer_sees_a_page_not_json(as_viewer):
    client = TestClient(app)
    response = client.post("/samples/1/save", headers={"accept": "text/html"})
    assert response.status_code == 403
    assert "not allowed to change records" in response.text

"""FastAPI app entrypoint for SAMS Web."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from starlette.types import Scope

from sams_web.config import get_settings
from sams_web.routers.api import router as api_router
from sams_web.routers.pages import router as pages_router
from sams_web.routers.pages_shared import templates


# --- Bundle config ----------------------------------------------------------
#
# The base template used to load five separate stylesheets and ten separate
# JS files, costing one HTTP request per file even after defer. These
# bundles concatenate them into one streamed response so the browser does
# one fetch per asset-kind. The bundle is built once per process at first
# request and cached in memory (`functools.lru_cache`). Source files in
# dev still live separately for editing; bumping the `css_v` Jinja global
# invalidates browser caches when sources change.

_STATIC_DIR = Path(__file__).resolve().parent / "static"

_CSS_BUNDLE_FILES: tuple[str, ...] = (
    # Order matters: tokens + base first, components second, page-specific
    # last so later rules can override earlier ones. style-benches.css is
    # NOT in the bundle — it's still loaded only by the bench page.
    "style-core.css",
    "style-tables.css",
    "style-detail-pages.css",
    "style-settings-kpi.css",
)

_JS_BUNDLE_FILES: tuple[str, ...] = (
    # Order matches the previous <script src> sequence in base.html;
    # each module attaches an installer to window.SAMSAppInstallers and
    # app.js fires them at DOMContentLoaded.
    "js/toast.js",
    "js/page-progress.js",
    "js/detail-shortcuts.js",
    "js/searchable-select.js",
    "js/history-back.js",
    "js/table-tools.js",
    "js/magic-nav-ui.js",
    "js/detail-edit-mode.js",
    "js/navigation-ui.js",
    "app.js",
)


def _minify_css(src: str) -> str:
    """Cheap CSS minification: strip /* ... */ comments and collapse
    insignificant whitespace. Conservative — it doesn't touch values,
    rewrite selectors, or merge rules. ~30 % byte reduction on our
    files in practice."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)        # comments
    src = re.sub(r"\s+", " ", src)                          # newlines/tabs/runs of space
    src = re.sub(r"\s*([{}:;,>+~])\s*", r"\1", src)         # space around punctuation
    src = re.sub(r";}", "}", src)                           # trailing semicolons
    return src.strip()


def _minify_js(src: str) -> str:
    """Cheap JS minification: strip block + line comments and collapse
    runs of whitespace. Does NOT rewrite identifiers (would break
    `data-`-attribute string lookups), so the savings are modest (~25 %).
    Pairs cleanly with gzip downstream."""
    # Strip /* ... */ comments. The regex is conservative — it doesn't
    # peek inside strings, but our JS uses single/double quotes and
    # template literals for strings rather than comment-like content.
    src = re.sub(r"/\*[\s\S]*?\*/", "", src)
    # Strip `// ...` line comments. Skip lines where `//` is inside a
    # string literal — a naive check looks for an unquoted match.
    out_lines: list[str] = []
    for line in src.splitlines():
        # Heuristic: count quotes before //. If even number of " or ',
        # the // is outside any string and starts a comment. This misses
        # template literals across lines, but our code doesn't put // inside
        # multi-line templates.
        idx = -1
        i = 0
        in_str = False
        str_ch = ""
        while i < len(line):
            c = line[i]
            if in_str:
                if c == "\\":
                    i += 2
                    continue
                if c == str_ch:
                    in_str = False
            else:
                if c in ('"', "'", "`"):
                    in_str = True
                    str_ch = c
                elif c == "/" and i + 1 < len(line) and line[i + 1] == "/":
                    idx = i
                    break
            i += 1
        if idx >= 0:
            line = line[:idx]
        out_lines.append(line)
    src = "\n".join(out_lines)
    # Collapse blank lines and trim trailing whitespace per line.
    src = re.sub(r"[ \t]+\n", "\n", src)
    src = re.sub(r"\n{2,}", "\n", src)
    return src.strip()


@lru_cache(maxsize=2)
def _build_bundle(kind: str) -> bytes:
    """Concat + minify the bundle files for `kind` in `("css", "js")`.
    Cached for the process lifetime; restart on source change in dev
    (uvicorn --reload picks this up automatically since `main.py` reloads
    too if you bump `css_v` in pages_shared.py)."""
    files = _CSS_BUNDLE_FILES if kind == "css" else _JS_BUNDLE_FILES
    minify = _minify_css if kind == "css" else _minify_js
    parts: list[str] = []
    for rel in files:
        text = (_STATIC_DIR / rel).read_text(encoding="utf-8")
        parts.append(f"/* --- {rel} --- */\n" + minify(text))
    return "\n".join(parts).encode("utf-8")


class CachedStaticFiles(StaticFiles):
    """StaticFiles + long-lived `Cache-Control` for every served file.

    The base template appends a `?v=<release-id>` query string to every
    `/static/*` URL (`css_v` Jinja global). Bumping that string is the
    cache-bust signal. With `immutable` + a one-year max-age, browsers
    skip the revalidation request entirely until the URL changes — which
    means a deploy-without-static-changes turns into pure HTML downloads
    after the first hit, and a deploy with new static assets fetches them
    exactly once via the new URL. Without this header the cache buster
    is decorative: browsers fall back to heuristic freshness or
    re-validate on every navigation.
    """

    async def get_response(self, path: str, scope: Scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response


def _build_not_found_context(request: Request) -> dict[str, object]:
    """Map the requested URL to a human-friendly 'not found' shape.

    The default FastAPI 404 returns a stark JSON or plain-HTML page that
    breaks the app shell — exactly the moment a user is most likely to
    think the app is broken. This builds a context tailored to whichever
    record-type the URL implies (sample / preparation / target / project
    / submitter), so the user sees the chrome they expect plus three
    CTAs that recover from the mistake."""
    path = request.url.path or "/"
    base = {
        "title": "Not Found",
        "requested_path": path,
        "back_url": "/",
    }
    if path.startswith("/samples"):
        return {
            **base,
            "entity_singular": "sample",
            "heading": "We couldn't find that sample",
            "subheading": "It may have been removed, or the number is wrong.",
            "newest_url": "/samples",
            "search_url": "/search?context=samples",
            "back_url": "/samples",
        }
    if path.startswith("/projects"):
        return {
            **base,
            "entity_singular": "project",
            "heading": "We couldn't find that project",
            "subheading": "It may have been removed, or the number is wrong.",
            "newest_url": "/projects",
            "search_url": "/search?context=projects",
            "back_url": "/projects",
        }
    if path.startswith("/submitters"):
        return {
            **base,
            "entity_singular": "submitter",
            "heading": "We couldn't find that submitter",
            "subheading": "It may have been removed, or the number is wrong.",
            "newest_url": "/submitters",
            "search_url": "/search?context=submitters",
            "back_url": "/submitters",
        }
    return {
        **base,
        "entity_singular": "page",
        "heading": "Page not found",
        "subheading": "The link you followed doesn't lead anywhere we recognise.",
        "newest_url": None,
        "search_url": "/search",
    }


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_title, debug=settings.debug)

    # Compress HTML/CSS/JS/JSON. minimum_size=500 avoids paying the gzip
    # cost on tiny responses (small JSON API replies). Starlette skips
    # gzip when the client doesn't send `Accept-Encoding: gzip`, so this
    # is safe for the rare client that can't decompress.
    app.add_middleware(GZipMiddleware, minimum_size=500)

    # Bundle routes must be registered BEFORE the `/static` mount —
    # Starlette mounts catch all sub-paths, so a mount at `/static`
    # eats `/static/bundle.css` before the decorated route gets a
    # chance unless we register decorated routes first.
    @app.get("/static/bundle.css")
    def css_bundle() -> Response:
        """Serve all global CSS as one minified file. ~1/5 the requests,
        ~2/3 the bytes of the un-minified individual files (before gzip).
        Caches like any other /static/* asset thanks to the `?v=` query
        string + the `Cache-Control: immutable` header below."""
        body = _build_bundle("css")
        return Response(
            content=body,
            media_type="text/css",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    @app.get("/static/bundle.js")
    def js_bundle() -> Response:
        """Serve all global JS as one minified file. See css_bundle()."""
        body = _build_bundle("js")
        return Response(
            content=body,
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", CachedStaticFiles(directory=str(static_dir)), name="static")

    app.include_router(pages_router)
    app.include_router(api_router)

    @app.exception_handler(404)
    @app.exception_handler(HTTPException)
    async def not_found_handler(request: Request, exc: HTTPException):
        """Render the styled `not_found.html` for any 404. Falls through
        to a JSON response for non-page routes (API endpoints) so machine
        clients still get a useful payload."""
        if isinstance(exc, HTTPException) and exc.status_code != 404:
            # Forward every other HTTPException untouched.
            return JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers=getattr(exc, "headers", None) or {},
            )
        accept = (request.headers.get("accept") or "").lower()
        path = request.url.path or "/"
        if path.startswith("/api/") or "application/json" in accept and "text/html" not in accept:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        context = {"request": request, **_build_not_found_context(request)}
        return templates.TemplateResponse("not_found.html", context, status_code=404)

    return app


app = create_app()

"""Technical failure details for the import wizard.

When parsing or committing fails, the operator gets a plain-language message
*and* a collapsible block of technical details they can copy to whoever
supports the system. The same details are written to the server log under the
same ``reference``, so one string finds both.

Bound parameters are deliberately left out: they hold customers' personal
data, and the statement plus the database's own message is what identifies
the problem (a too-long value, an unknown column, a lost connection).
"""

from __future__ import annotations

import traceback
import uuid
from datetime import datetime
from typing import Any

_MAX_TEXT = 1500
_APP_MARKER = "sams_web"


def _clip(text: Any, limit: int = _MAX_TEXT) -> str:
    value = str(text)
    return value if len(value) <= limit else value[:limit] + f"… [{len(value) - limit} more characters]"


def _innermost_app_frame(exc: BaseException) -> str | None:
    """`file:line in function` of the deepest frame inside this application."""
    frames = [f for f in traceback.extract_tb(exc.__traceback__) if _APP_MARKER in f.filename.replace("\\", "/")]
    if not frames:
        return None
    frame = frames[-1]
    path = frame.filename.replace("\\", "/")
    short = path[path.rindex(_APP_MARKER):]
    return f"{short}:{frame.lineno} in {frame.name}()"


def describe_failure(exc: BaseException, *, stage: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
    """A JSON-serialisable description of `exc` for the browser and the log."""
    details: dict[str, Any] = {
        "reference": uuid.uuid4().hex[:8].upper(),
        "time": datetime.now().isoformat(timespec="seconds"),
        "stage": stage,
        "error_type": f"{type(exc).__module__}.{type(exc).__name__}",
        "message": _clip(exc) or "(no message)",
    }
    location = _innermost_app_frame(exc)
    if location:
        details["location"] = location

    row = getattr(exc, "import_row", None)
    if row:
        details["sheet_row"], details["sample_label"] = row

    # SQLAlchemy wraps the driver's error: surface both, minus parameters.
    original = getattr(exc, "orig", None)
    if original is not None:
        details["database_error"] = _clip(f"{type(original).__name__}: {original}")
    statement = getattr(exc, "statement", None)
    if statement:
        details["sql"] = _clip(" ".join(str(statement).split()))

    causes: list[str] = []
    cause = exc.__cause__ or exc.__context__
    while cause is not None and len(causes) < 3:
        causes.append(_clip(f"{type(cause).__name__}: {cause}", 400))
        cause = cause.__cause__ or cause.__context__
    if causes:
        details["caused_by"] = causes

    if context:
        details["context"] = {k: v for k, v in context.items() if v not in (None, "")}
    return details


def format_for_log(details: dict[str, Any]) -> str:
    return " | ".join(f"{k}={v}" for k, v in details.items())

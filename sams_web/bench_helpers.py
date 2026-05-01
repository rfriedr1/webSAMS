"""Shared helpers for bench workflow selection and queue navigation."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass
class BenchSaveOutcome:
    """Result of applying a single bench-entry submit.

    `next_cursor` is populated only if `action == "save_next"` AND a next
    queue entry exists. The router translates this into a redirect URL with
    the new cursor; otherwise it redirects back to the same cursor with a
    saved=true flag.
    """

    success: bool
    field_errors: dict[str, str] = field(default_factory=dict)
    save_error: str | None = None
    next_cursor: tuple[int, ...] | None = None


def select_by_number(items: Sequence[T], requested_number: int | None, attr_name: str) -> T | None:
    if requested_number is None:
        return None
    return next((item for item in items if getattr(item, attr_name) == requested_number), None)


def select_preparation(
    preparations: Sequence[T],
    requested_prep_nr: int | None,
    *,
    open_attr_name: str | None = None,
) -> T | None:
    selected = select_by_number(preparations, requested_prep_nr, "prep_nr")
    if selected is not None:
        return selected
    if open_attr_name is not None:
        open_items = [item for item in preparations if getattr(item, open_attr_name) is None]
        if open_items:
            return open_items[-1]
    return preparations[-1] if preparations else None


def select_target(targets: Sequence[T], requested_target_nr: int | None) -> T | None:
    selected = select_by_number(targets, requested_target_nr, "target_nr")
    if selected is not None:
        return selected
    return targets[-1] if targets else None


def queue_tuples(
    rows: Iterable[dict[str, Any]],
    *keys: str,
) -> list[tuple[int, ...]]:
    queue: list[tuple[int, ...]] = []
    for row in rows:
        try:
            queue.append(tuple(int(row.get(key)) for key in keys))
        except (TypeError, ValueError):
            continue
    return queue


def next_queue_entry(queue: Sequence[tuple[int, ...]], current: tuple[int, ...]) -> tuple[int, ...] | None:
    if not queue:
        return None
    for index, item in enumerate(queue):
        if item == current:
            return queue[index + 1] if index + 1 < len(queue) else None
    for item in queue:
        if item > current:
            return item
    return None

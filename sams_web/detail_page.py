"""Detail-page context builder.

Replaces the per-entity `_build_*_context` / `build_*_detail_context`
functions that previously lived as five near-identical builders across
`routers/detail_contexts.py` and `routers/pages_users_projects.py`. Each
detail page (sample / preparation / target / project / submitter) now
ships a `DetailPageConfig` declaring its prefix, source-of-truth
`DetailUpdateConfig`, edit-form id, sections builder, and (optionally)
its dropdown getter. Routes call `build_detail_page_context` to produce
the shared template-context shape and merge in any page-specific extras.

The pulled-from-config read-only and required field sets fix a latent
mismatch where the read-side previously declared its own constants
(missing the BATS-owned target/sample fields), letting the UI render
editors for fields the write-side then silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from fastapi import Request

from sams_web.detail_update import DetailUpdateConfig

if TYPE_CHECKING:
    from sams_web.services import SamsService


SectionsBuilder = Callable[[Any], list[dict[str, Any]]]
SelectOptionsGetter = Callable[["SamsService"], dict[str, list[str]]]


@dataclass(frozen=True)
class DetailPageConfig:
    """Per-entity detail-page configuration.

    `name` is the template-key prefix (e.g. "sample" → `sample_field_errors`,
    `sample_saved`, etc.). `update_config` is the source of truth for the
    write-side rules; the page builder derives the template's `read_only_fields`
    and `required_fields` from it so the view and the write path agree.
    """

    name: str
    update_config: DetailUpdateConfig
    edit_form_id: str
    sections_builder: SectionsBuilder
    select_options_getter: SelectOptionsGetter | None = None


@dataclass
class NavCursor:
    """Prev/next/count/max navigation values for a detail page."""

    previous_nr: int | None
    next_nr: int | None
    count: int
    max_nr: int


@dataclass
class EditFormState:
    """Edit-form display state passed through the GET/POST cycle."""

    saved: bool = False
    save_error: str | None = None
    field_errors: dict[str, str] | None = None
    form_values: dict[str, str] | None = None
    edit_initial_mode: str = "view"


def _read_only_fields_for_template(update_config: DetailUpdateConfig) -> tuple[str, ...]:
    """The template uses bare field names (no form prefix) to suppress
    editor rendering. Comes straight from `update_config.read_only_fields`.
    """
    return tuple(sorted(update_config.read_only_fields))


def _required_fields_for_template(prefix: str, update_config: DetailUpdateConfig) -> tuple[str, ...]:
    """Template's required-field markers use the full form-key namespace
    (e.g. `sample__type`). Includes parent-imposed required fields from
    related-entity rules (e.g. sample requires its parent project's in_date)
    namespaced via the related rule's prefix."""
    keys: list[str] = []
    for field_name, _message in update_config.required_fields:
        keys.append(f"{prefix}{field_name}")
    for rule in update_config.related:
        for field_name, _message in rule.extra_required_fields:
            keys.append(f"{prefix}{rule.prefix}{field_name}")
    return tuple(keys)


def build_detail_page_context(
    request: Request,
    config: DetailPageConfig,
    *,
    entity: Any,
    cursor: NavCursor,
    edit_state: EditFormState,
    service: "SamsService",
    sections_kwargs: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Produce the shared detail-page template context.

    Generates these keys (where `<n>` = `config.name`):

    - `request`, `<n>` (the entity reference)
    - `<n>_sections`, `<n>_edit_form_id`
    - `<n>_read_only_fields`, `<n>_required_fields`, `<n>_select_options`
    - `<n>_field_errors`, `<n>_form_values`
    - `<n>_save_error`, `<n>_saved`, `<n>_edit_initial_mode`
    - `previous_<n>_nr`, `next_<n>_nr`, `<n>_count`, `max_<n>_nr`

    Merges `extra` (page-specific keys: related entities, display
    formatters, creation notices, etc.) on top of the standard keys, so
    callers can override any standard key when they have a reason to.
    """
    name = config.name
    sections = config.sections_builder(entity, **(sections_kwargs or {}))
    select_options: dict[str, list[str]] = (
        config.select_options_getter(service) if config.select_options_getter else {}
    )

    standard: dict[str, object] = {
        "request": request,
        name: entity,
        f"{name}_sections": sections,
        f"{name}_edit_form_id": config.edit_form_id,
        f"{name}_read_only_fields": _read_only_fields_for_template(config.update_config),
        f"{name}_required_fields": _required_fields_for_template(
            config.update_config.prefix, config.update_config
        ),
        f"{name}_select_options": select_options,
        f"{name}_field_errors": edit_state.field_errors or {},
        f"{name}_form_values": edit_state.form_values or {},
        f"{name}_save_error": edit_state.save_error,
        f"{name}_saved": edit_state.saved,
        f"{name}_edit_initial_mode": edit_state.edit_initial_mode,
        f"previous_{name}_nr": cursor.previous_nr,
        f"next_{name}_nr": cursor.next_nr,
        f"{name}_count": cursor.count,
        f"max_{name}_nr": cursor.max_nr,
    }

    if extra:
        standard.update(extra)

    return standard


__all__ = [
    "DetailPageConfig",
    "NavCursor",
    "EditFormState",
    "build_detail_page_context",
]

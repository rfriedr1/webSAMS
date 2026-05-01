"""Generic detail-update primitive for single-entity form submissions.

Replaces the duplicated `update_*_detail` logic that previously lived as five
near-identical methods on `SamsService`. Each entity ships a
`DetailUpdateConfig` declaring its prefix, read-only fields, dropdowns,
required fields, post-rules, and any related-entity passthroughs. The
orchestrator decodes the form, coerces values, validates, runs post-rules
(which may both reject and mutate), and flushes the session. It does NOT
commit -- callers commit on success.

See ADR-0001 (submitter naming context), ADR-0003 (BATS-owned read-only
fields, plumbed via `read_only_fields`), and ADR-0004 (project auto-close
implemented as a post-rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Iterable

from sqlalchemy.inspection import inspect as sa_inspect
from sqlalchemy.sql.sqltypes import Date as SQLDate
from sqlalchemy.sql.sqltypes import DateTime as SQLDateTime
from sqlalchemy.sql.sqltypes import Float as SQLFloat
from sqlalchemy.sql.sqltypes import Integer as SQLInteger


# ---- Public types ---------------------------------------------------------

DropdownGetter = Callable[[Any], Iterable[str]]
"""Given a repo, return the allowed string values for a field."""

RelatedLookup = Callable[[Any, Any], Any]
"""Given (parent_entity, repo), return the loaded child entity (or None)."""


@dataclass
class RuleContext:
    """Argument bundle passed to each post-rule.

    `updates` is the working dict of staged field changes for the parent;
    `related_updates` maps a `RelatedEntityRule.prefix` to its working dict.
    `related_entities` carries the loaded child entities (or None if missing).
    """

    entity: Any
    updates: dict[str, Any]
    related_updates: dict[str, dict[str, Any]]
    related_entities: dict[str, Any]
    repo: Any


@dataclass
class RuleOutcome:
    """Return shape for a post-rule.

    - Non-empty `field_errors` short-circuits the pipeline; remaining rules
      do not run and nothing is written.
    - `updates` and `related_updates`, when not None, replace the current
      working dicts.
    """

    field_errors: dict[str, str] = field(default_factory=dict)
    updates: dict[str, Any] | None = None
    related_updates: dict[str, dict[str, Any]] | None = None


PostRule = Callable[[RuleContext], RuleOutcome]


@dataclass(frozen=True)
class RelatedEntityRule:
    """Declares that form fields with `<parent_prefix><prefix><field>` map
    onto a related entity reached via `lookup`. The child's full pipeline
    (coercion, dropdowns, post-rules) runs against its slice of the form.

    `extra_required_fields` lets the parent impose additional required-field
    rules on the child that the child's own config does not enforce when
    accessed directly. Used e.g. for the sample form requiring a project's
    in_date / desired_date that aren't required on a standalone project edit.
    """

    prefix: str
    config: "DetailUpdateConfig"
    lookup: RelatedLookup
    missing_error: str
    extra_required_fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DetailUpdateConfig:
    """Per-entity configuration passed to `apply_detail_update`.

    `required_fields` is a tuple of `(field_name, error_message)` pairs so
    each required field can carry its own user-facing message. Field names
    are bare (no form prefix); the orchestrator namespaces errors at output
    time.
    """

    model: type
    prefix: str
    read_only_fields: frozenset[str] = frozenset()
    dropdown_getters: dict[str, DropdownGetter] = field(default_factory=dict)
    required_fields: tuple[tuple[str, str], ...] = ()
    post_rules: tuple[PostRule, ...] = ()
    related: tuple[RelatedEntityRule, ...] = ()


@dataclass
class DetailUpdateResult:
    saved: bool
    field_errors: dict[str, str]
    save_error: str | None


# ---- Module-private helpers ----------------------------------------------


def model_columns(model: type) -> dict[str, Any]:
    mapper = sa_inspect(model).mapper
    return {attr.key: attr.columns[0] for attr in mapper.column_attrs}


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped if stripped != "" else None


def coerce_column_value(column: Any, raw_value: str | None) -> tuple[Any, str | None]:
    normalized = normalize_text(raw_value)
    if normalized is None:
        return None, None
    try:
        if isinstance(column.type, SQLInteger):
            return int(normalized), None
        if isinstance(column.type, SQLFloat):
            return float(normalized), None
        if isinstance(column.type, SQLDate):
            return date.fromisoformat(normalized), None
        if isinstance(column.type, SQLDateTime):
            return datetime.fromisoformat(normalized), None
    except ValueError:
        return None, "Invalid value format."
    return normalized, None


def _slice_form(form_data: dict[str, str], full_prefix: str) -> dict[str, str]:
    """Return form entries whose key starts with `full_prefix`, with the
    prefix stripped. Non-matching keys are dropped."""
    return {
        key.removeprefix(full_prefix): value
        for key, value in form_data.items()
        if key.startswith(full_prefix)
    }


def _decode_level(
    config: DetailUpdateConfig,
    sliced_form: dict[str, str],
    repo: Any,
    full_form_prefix: str,
    skip_related: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, str]]:
    """Decode + per-field validate one level (a parent or a child).

    Returns `(updates, related_updates, field_errors)`. Related updates are
    nested by their `RelatedEntityRule.prefix`. Field-error keys are full
    form keys (using `full_form_prefix`) so the form can highlight the
    correct input on render.

    Skipped silently: read-only fields, columns not on the model, fields
    whose name is the entity's primary key (those are immutable and don't
    belong in update form data).
    """
    columns = model_columns(config.model)
    pk_keys = {col.key for col in sa_inspect(config.model).mapper.primary_key}

    updates: dict[str, Any] = {}
    related_updates: dict[str, dict[str, Any]] = {rule.prefix: {} for rule in config.related}
    field_errors: dict[str, str] = {}

    # First, peel off any related-entity slices.
    related_slices: dict[str, dict[str, str]] = {}
    for rule in config.related:
        rel_slice = _slice_form(sliced_form, rule.prefix)
        related_slices[rule.prefix] = rel_slice

    # Anything that matched a related prefix is removed from the parent slice.
    parent_slice = {
        k: v
        for k, v in sliced_form.items()
        if not any(k.startswith(rule.prefix) for rule in config.related)
    }

    # Per-field decode for the parent level.
    for field_key, raw_value in parent_slice.items():
        if field_key in pk_keys:
            continue
        if field_key in config.read_only_fields:
            continue

        column = columns.get(field_key)
        if column is None:
            continue

        coerced, error = coerce_column_value(column, raw_value)
        if error is not None:
            field_errors[full_form_prefix + field_key] = error
            continue

        getter = config.dropdown_getters.get(field_key)
        if getter is not None and coerced is not None:
            allowed = {v for v in getter(repo) if isinstance(v, str) and v.strip()}
            if str(coerced) not in allowed:
                field_errors[full_form_prefix + field_key] = "Value must be selected from the dropdown list."
                continue

        updates[field_key] = coerced

    # Recurse into each related rule's slice. The child's own pipeline runs.
    skip_related = skip_related or set()
    for rule in config.related:
        if rule.prefix in skip_related:
            continue
        child_slice = related_slices[rule.prefix]
        if not child_slice:
            continue
        child_full_prefix = full_form_prefix + rule.prefix
        child_updates, child_grandchild_updates, child_errors = _decode_level(
            rule.config, child_slice, repo, child_full_prefix
        )
        related_updates[rule.prefix] = child_updates
        # Grandchildren aren't supported today; flag if anything sneaks in.
        if any(child_grandchild_updates.values()):
            field_errors[child_full_prefix + "__nested__"] = "Nested related fields are not supported."
        field_errors.update(child_errors)

    return updates, related_updates, field_errors


def _check_required(
    config: DetailUpdateConfig,
    entity: Any,
    updates: dict[str, Any],
    full_form_prefix: str,
    extra_required: tuple[tuple[str, str], ...] = (),
) -> dict[str, str]:
    """Required fields must be non-empty after the proposed updates.

    When `entity is None` (orphan related entity), each required field
    fires its message regardless of the form input -- the value cannot be
    populated without the missing parent. Callers can pass `extra_required`
    to layer parent-imposed required rules on top of the config's own.
    """
    errors: dict[str, str] = {}
    all_required = list(config.required_fields) + list(extra_required)
    for field_name, message in all_required:
        full_key = full_form_prefix + field_name
        if entity is None:
            errors[full_key] = message
            continue
        if field_name in updates:
            value = updates[field_name]
        else:
            value = getattr(entity, field_name, None)
        is_blank = value is None or (isinstance(value, str) and value.strip() == "")
        if is_blank:
            errors[full_key] = message
    return errors


# ---- The orchestrator -----------------------------------------------------


def apply_detail_update(
    config: DetailUpdateConfig,
    entity_nr: Any,
    form_data: dict[str, str],
    repo: Any,
) -> DetailUpdateResult:
    """Decode `form_data`, validate, run post-rules, and apply to the
    session. Flushes; does not commit. Caller commits on `result.saved`.

    `entity_nr` is the primary key of the parent entity. For composite keys
    (e.g. preparation, target) pass a tuple; the repo's `get_<model>` lookup
    is responsible for unpacking.
    """
    entity = _load_entity(config.model, entity_nr, repo)
    if entity is None:
        return DetailUpdateResult(False, {}, f"{config.model.__name__} not found.")

    # Eager-load related entities (matches today's behaviour: child loaded
    # whenever parent FK is set, even if no child fields were submitted, so
    # cross-validators can read existing values).
    related_entities: dict[str, Any] = {}
    for rule in config.related:
        related_entities[rule.prefix] = rule.lookup(entity, repo)

    sliced = _slice_form(form_data, config.prefix)

    # If a child slice has fields but its loader returned None (orphan
    # related entity), surface a per-field error for each child field.
    # Skip decoding the rest of this child to avoid noise.
    forced_errors: dict[str, str] = {}
    skip_related: set[str] = set()
    for rule in config.related:
        child_slice = _slice_form(sliced, rule.prefix)
        if child_slice and related_entities[rule.prefix] is None:
            for child_field in child_slice:
                forced_errors[config.prefix + rule.prefix + child_field] = rule.missing_error
            skip_related.add(rule.prefix)

    updates, related_updates, field_errors = _decode_level(
        config, sliced, repo, full_form_prefix=config.prefix, skip_related=skip_related
    )
    field_errors.update(forced_errors)

    # Required-field check: parent + each related (loaded or missing).
    field_errors.update(_check_required(config, entity, updates, config.prefix))
    for rule in config.related:
        child_entity = related_entities[rule.prefix]
        child_full_prefix = config.prefix + rule.prefix
        child_updates = related_updates.get(rule.prefix, {})
        field_errors.update(
            _check_required(
                rule.config,
                child_entity,
                child_updates,
                child_full_prefix,
                extra_required=rule.extra_required_fields,
            )
        )

    if field_errors:
        return DetailUpdateResult(False, field_errors, None)

    # Children's post-rules first, then the parent's. Each level's rules see
    # only its own `updates` view via RuleContext; cross-level coordination
    # is intentionally not supported.
    for rule in config.related:
        child_entity = related_entities[rule.prefix]
        if child_entity is None:
            continue
        child_full_prefix = config.prefix + rule.prefix
        outcome = _run_post_rules(
            rule.config,
            child_entity,
            related_updates[rule.prefix],
            related_updates_below={},  # children currently never have grandchildren
            related_entities_below={},
            repo=repo,
            full_form_prefix=child_full_prefix,
        )
        if outcome.field_errors:
            return DetailUpdateResult(False, outcome.field_errors, None)
        if outcome.updates is not None:
            related_updates[rule.prefix] = outcome.updates

    parent_outcome = _run_post_rules(
        config,
        entity,
        updates,
        related_updates_below=related_updates,
        related_entities_below=related_entities,
        repo=repo,
        full_form_prefix=config.prefix,
    )
    if parent_outcome.field_errors:
        return DetailUpdateResult(False, parent_outcome.field_errors, None)
    if parent_outcome.updates is not None:
        updates = parent_outcome.updates
    if parent_outcome.related_updates is not None:
        related_updates = parent_outcome.related_updates

    # Apply.
    for key, value in updates.items():
        setattr(entity, key, value)
    for prefix, child_updates in related_updates.items():
        child_entity = related_entities.get(prefix)
        if child_entity is None or not child_updates:
            continue
        for key, value in child_updates.items():
            setattr(child_entity, key, value)

    repo.session.flush()
    return DetailUpdateResult(True, {}, None)


def _run_post_rules(
    config: DetailUpdateConfig,
    entity: Any,
    updates: dict[str, Any],
    related_updates_below: dict[str, dict[str, Any]],
    related_entities_below: dict[str, Any],
    repo: Any,
    full_form_prefix: str,
) -> RuleOutcome:
    """Run a level's post-rules in order. Field-error keys returned by rules
    are namespaced (re-prefixed with `full_form_prefix`) so they line up
    with the original form input names."""
    working_updates = dict(updates)
    working_related = {k: dict(v) for k, v in related_updates_below.items()}
    for rule in config.post_rules:
        ctx = RuleContext(
            entity=entity,
            updates=working_updates,
            related_updates=working_related,
            related_entities=related_entities_below,
            repo=repo,
        )
        outcome = rule(ctx)
        if outcome.field_errors:
            return RuleOutcome(
                field_errors={full_form_prefix + k: v for k, v in outcome.field_errors.items()},
            )
        if outcome.updates is not None:
            working_updates = outcome.updates
        if outcome.related_updates is not None:
            working_related = outcome.related_updates
    return RuleOutcome(updates=working_updates, related_updates=working_related)


def _load_entity(model: type, entity_nr: Any, repo: Any) -> Any:
    """Look up the entity via the repo's `get_<lowercased model name>` method
    if available, falling back to `session.get` for simple primary keys."""
    method_name = f"get_{model.__name__.lower()}"
    method = getattr(repo, method_name, None)
    if method is not None:
        if isinstance(entity_nr, tuple):
            return method(*entity_nr)
        return method(entity_nr)
    return repo.session.get(model, entity_nr)

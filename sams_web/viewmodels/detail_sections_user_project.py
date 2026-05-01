"""Submitter and project detail section definitions, plus their detail-update configs."""

from __future__ import annotations

from typing import Any

from sams_web.detail_page import DetailPageConfig
from sams_web.detail_update import (
    DetailUpdateConfig,
    RuleContext,
    RuleOutcome,
)
from sams_web.models import Project, Submitter
from sams_web.viewmodels.detail_sections_common import SectionSpec, build_sections

USER_FIELD_LABELS = {
    "user_nr": "Submitter #",
    "first_name": "First Name",
    "last_name": "Last Name",
    "organisation": "Organisation",
    "institute": "Institute",
    "address_1": "Address 1",
    "address_2": "Address 2",
    "town": "Town",
    "postcode": "Postcode",
    "country": "Country",
    "phone_1": "Phone 1",
    "phone_2": "Phone 2",
    "fax": "Fax",
    "email": "Email",
    "www": "Website",
    "account": "Account",
    "invoice": "Invoice",
    "correspondance": "Correspondence",
    "user_comment": "Comment",
    "title": "Title",
    "language": "Language",
    "salutation": "Salutation",
}

USER_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Identity", "Personal and language details.", ("user_nr", "title", "salutation", "first_name", "last_name", "language")),
    ("Organisation", "Institution and billing settings.", ("organisation", "institute", "account", "invoice", "correspondance")),
    ("Contact", "Direct communication channels.", ("email", "phone_1", "phone_2", "fax", "www")),
    ("Address", "Postal address information.", ("address_1", "address_2", "town", "postcode", "country")),
    ("Notes", "Additional comments from the submitter record.", ("user_comment",)),
)


def user_field_kind(key: str) -> str:
    if key in {"invoice", "correspondance"}:
        return "boolean"
    if key == "email":
        return "email"
    if key == "www":
        return "url"
    return "text"


def format_user_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if key in {"invoice", "correspondance"}:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    return value


def build_user_sections(user: Any) -> list[dict[str, Any]]:
    return build_sections(
        user,
        field_labels=USER_FIELD_LABELS,
        section_specs=USER_SECTION_SPECS,
        kind_resolver=user_field_kind,
        value_formatter=format_user_value,
        include_other=True,
        other_title="Other",
        other_description="Additional fields available in the user record.",
    )


PROJECT_FIELD_LABELS = {
    "project_nr": "Project #",
    "project": "Project Name",
    "user_nr": "Submitter #",
    "invoice_nr": "Invoice Submitter #",
    "in_date": "In Date",
    "out_date": "Out Date",
    "desired_date": "Desired Date",
    "priority": "Priority",
    "report_type": "Report Type",
    "letter": "Letter",
    "project_comment": "Project Comment",
    "status": "Status",
    "price": "Price",
    "project_type": "Project Type",
    "research": "Research",
    "report": "Report",
    "invoice": "Invoice",
    "auftrags_nr": "Order ID (AuftragsNr)",
    "invoice_date": "Invoice Date",
    "advisor": "Advisor",
    "sample_storage_loc": "Sample Storage Location",
    "free_of_charge": "Free Of Charge",
    "order_nr": "Order Number",
    "supervisor": "Supervisor",
    "return_to_sender": "Return To Sender",
    "returned_to_sender": "Returned To Sender",
    "prep_return_to_sender": "Prep Return To Sender",
    "prep_returned_to_sender": "Prep Returned To Sender",
}

PROJECT_SECTION_SPECS: tuple[SectionSpec, ...] = (
    ("Core", "Core project identity and classification.", ("project_nr", "project", "status", "priority", "project_type", "research", "report_type")),
    ("Submitter", "Assigned submitter and responsible staff.", ("user_nr", "invoice_nr", "advisor", "supervisor")),
    ("Timeline", "Planning and delivery dates.", ("in_date", "desired_date", "out_date", "invoice_date")),
    ("Commercial", "Billing and order metadata.", ("price", "invoice", "free_of_charge", "auftrags_nr", "order_nr", "letter")),
    ("Logistics", "Storage and return logistics.", ("sample_storage_loc", "return_to_sender", "returned_to_sender", "prep_return_to_sender", "prep_returned_to_sender")),
    ("Reporting", "Output and notes tied to the project.", ("report",)),
)

PROJECT_BOOLEAN_FIELDS = {
    "invoice",
    "free_of_charge",
    "return_to_sender",
    "returned_to_sender",
    "prep_return_to_sender",
    "prep_returned_to_sender",
}


def project_field_kind(key: str) -> str:
    if key in PROJECT_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"project_comment", "report", "letter"}:
        return "multiline"
    if "date" in key or key in {"in_date", "out_date", "desired_date"}:
        return "date"
    return "text"


def format_project_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if key in PROJECT_BOOLEAN_FIELDS:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    return value


def build_project_sections(project: Any) -> list[dict[str, Any]]:
    return build_sections(
        project,
        field_labels=PROJECT_FIELD_LABELS,
        section_specs=PROJECT_SECTION_SPECS,
        kind_resolver=project_field_kind,
        value_formatter=format_project_value,
        include_other=False,
        other_title="Other",
        other_description="Additional fields available in this project record.",
    )


# ---- Detail-update configs ------------------------------------------------


def _is_prepaid_status(status: str | None) -> bool:
    # Per ADR-0004, `prepaid` is a billing flag riding in project_t.status;
    # auto-close on out_date must leave it untouched.
    return bool(status) and status.strip().lower() == "prepaid"


def _pick_closed_project_status(statuses: list[str]) -> str | None:
    cleaned = [status.strip() for status in statuses if status and status.strip()]
    if not cleaned:
        return None
    lowered = {status.lower(): status for status in cleaned}
    exact = lowered.get("closed")
    if exact is not None:
        return exact
    for status in cleaned:
        if "closed" in status.lower():
            return status
    return None


def validate_project_date_ordering(ctx: RuleContext) -> RuleOutcome:
    in_date = ctx.updates.get("in_date", ctx.entity.in_date)
    desired = ctx.updates.get("desired_date", ctx.entity.desired_date)
    out_date = ctx.updates.get("out_date", ctx.entity.out_date)

    errors: dict[str, str] = {}
    if in_date is not None and desired is not None and desired < in_date:
        errors["desired_date"] = "Desired Date must be on or after In Date."
    if in_date is not None and out_date is not None and out_date < in_date:
        errors["out_date"] = "Out Date must be on or after In Date."
    return RuleOutcome(field_errors=errors)


def apply_auto_close_on_out_date(ctx: RuleContext) -> RuleOutcome:
    # ADR-0004: when out_date is set, flip status to closed unless prepaid.
    out_date_changed = "out_date" in ctx.updates and ctx.updates["out_date"] != ctx.entity.out_date
    new_out_date = ctx.updates.get("out_date", ctx.entity.out_date)
    effective_status = ctx.updates.get("status", ctx.entity.status)

    if not out_date_changed or new_out_date is None or _is_prepaid_status(effective_status):
        return RuleOutcome()

    statuses = ctx.repo.get_project_statuses()
    closed_status = _pick_closed_project_status(statuses)
    if closed_status is None:
        return RuleOutcome(
            field_errors={"out_date": "Out Date requires a closing status configured in projectstatus_t."}
        )

    revised = dict(ctx.updates)
    revised["status"] = closed_status
    return RuleOutcome(updates=revised)


SUBMITTER_DETAIL = DetailUpdateConfig(
    model=Submitter,
    prefix="user__",
    read_only_fields=frozenset({"user_nr"}),
)


PROJECT_DETAIL = DetailUpdateConfig(
    model=Project,
    prefix="project__",
    read_only_fields=frozenset({"project_nr", "user_nr"}),
    dropdown_getters={
        "status": lambda repo: list(repo.get_project_statuses()),
        "project_type": lambda repo: list(repo.get_project_types()),
        "research": lambda repo: list(repo.get_research_values()),
        "report_type": lambda repo: list(repo.get_report_types()),
    },
    post_rules=(
        validate_project_date_ordering,
        apply_auto_close_on_out_date,
    ),
)


# ---- Detail-page configs (read side) -------------------------------------


SUBMITTER_DETAIL_PAGE = DetailPageConfig(
    name="submitter",
    update_config=SUBMITTER_DETAIL,
    edit_form_id="submitter-detail-edit-form",
    sections_builder=build_user_sections,
)


PROJECT_DETAIL_PAGE = DetailPageConfig(
    name="project",
    update_config=PROJECT_DETAIL,
    edit_form_id="project-detail-edit-form",
    sections_builder=build_project_sections,
    select_options_getter=lambda service: service.get_project_edit_select_options(),
)

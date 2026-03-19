"""User and project detail section definitions."""

from __future__ import annotations

from typing import Any

from sams_web.viewmodels.detail_sections_common import SectionSpec, build_sections

USER_FIELD_LABELS = {
    "user_nr": "User #",
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
    "user_nr": "User #",
    "invoice_nr": "Invoice User #",
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
    ("User", "Assigned user and responsible staff.", ("user_nr", "invoice_nr", "advisor", "supervisor")),
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

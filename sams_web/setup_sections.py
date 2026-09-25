"""Setup section metadata and discovery."""

from __future__ import annotations

from dataclasses import dataclass


SETUP_SECTION_STANDARD_THRESHOLDS = "standard_inventory_thresholds"
SETUP_SECTION_GRAPHITIZATION_SYSTEMS = "graphitization_systems"
SETUP_SECTION_LAB_WARNING_THRESHOLDS = "lab_warning_thresholds"
SETUP_SECTION_IMPORT_HEADINGS = "import_column_headings"
SETUP_SECTION_EMAIL = "email_settings"


@dataclass(frozen=True)
class SetupSection:
    key: str
    title: str
    description: str
    editable: bool
    status: str
    form_action: str | None = None


SETUP_SECTIONS: tuple[SetupSection, ...] = (
    SetupSection(
        key=SETUP_SECTION_STANDARD_THRESHOLDS,
        title="Standard Inventory Thresholds",
        description="Thresholds that control inventory warning colors in the dashboard.",
        editable=True,
        status="active",
        form_action="/setup/standard_inventory_thresholds",
    ),
    SetupSection(
        key=SETUP_SECTION_GRAPHITIZATION_SYSTEMS,
        title="Graphitization Systems",
        description="Configurable system suffixes used to build graph batch names (graph_YYMMDD_system).",
        editable=True,
        status="active",
        form_action="/setup/graphitization_systems",
    ),
    SetupSection(
        key=SETUP_SECTION_LAB_WARNING_THRESHOLDS,
        title="Lab Warning Thresholds",
        description="Quality thresholds that drive in-app warning highlights on lab detail pages.",
        editable=True,
        status="active",
        form_action="/setup/lab_warning_thresholds",
    ),
    SetupSection(
        key=SETUP_SECTION_IMPORT_HEADINGS,
        title="Import Column Headings",
        description="Extra spellings the sample importer accepts for each column, plus additional columns you define yourself, so a customer's own wording is recognised automatically.",
        editable=True,
        status="active",
        form_action="/setup/import_column_headings",
    ),
    SetupSection(
        key=SETUP_SECTION_EMAIL,
        title="E-mail",
        description="Outgoing mail server and the confirmation templates sent to submitters after an import.",
        editable=True,
        status="active",
        form_action="/setup/email_settings",
    ),
    SetupSection(
        key="lab_defaults",
        title="Lab Defaults",
        description="Future section for global defaults used in project and sample creation.",
        editable=False,
        status="planned",
    ),
)

SETUP_SECTION_MAP: dict[str, SetupSection] = {section.key: section for section in SETUP_SECTIONS}

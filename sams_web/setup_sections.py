"""Setup section metadata and discovery."""

from __future__ import annotations

from dataclasses import dataclass


SETUP_SECTION_STANDARD_THRESHOLDS = "standard_inventory_thresholds"
SETUP_SECTION_GRAPHITIZATION_SYSTEMS = "graphitization_systems"


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
        key="import_profiles",
        title="Import Profiles",
        description="Future section for mapping and profile templates per laboratory form.",
        editable=False,
        status="planned",
    ),
    SetupSection(
        key="notifications",
        title="Notifications",
        description="Future section for email alerts and warning rules.",
        editable=False,
        status="planned",
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

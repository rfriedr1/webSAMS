"""Detail section definitions and formatting for server-rendered pages."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Callable, Iterable

from sqlalchemy.inspection import inspect

SectionSpec = tuple[str, str, tuple[str, ...]]
Row = dict[str, Any]
RowsBySectionFactory = Callable[[str], Iterable[Row]]


def _mapped_values(entity: Any) -> dict[str, Any]:
    """Return mapped ORM column values keyed by attribute name."""
    mapper = inspect(entity).mapper
    return {attr.key: getattr(entity, attr.key) for attr in mapper.column_attrs}


def _default_label(key: str) -> str:
    return key.replace("_", " ").title()


def _build_sections(
    entity: Any,
    *,
    field_labels: dict[str, str],
    section_specs: tuple[SectionSpec, ...],
    kind_resolver: Callable[[str], str],
    value_formatter: Callable[[str, Any], Any],
    include_other: bool = True,
    other_title: str = "Other",
    other_description: str = "Additional fields available in this record.",
    other_excluded_keys: set[str] | None = None,
    extra_rows_by_section: RowsBySectionFactory | None = None,
) -> list[dict[str, Any]]:
    values_by_key = _mapped_values(entity)
    sections: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    excluded_keys = other_excluded_keys or set()

    for title, description, keys in section_specs:
        rows: list[Row] = []
        for key in keys:
            if key not in values_by_key:
                continue
            seen_keys.add(key)
            rows.append(
                {
                    "key": key,
                    "label": field_labels.get(key, _default_label(key)),
                    "kind": kind_resolver(key),
                    "raw_value": values_by_key[key],
                    "value": value_formatter(key, values_by_key[key]),
                }
            )

        if extra_rows_by_section:
            rows.extend(extra_rows_by_section(title))

        if rows:
            sections.append({"title": title, "description": description, "rows": rows})

    if include_other:
        other_rows = [
            {
                "key": key,
                "label": field_labels.get(key, _default_label(key)),
                "kind": kind_resolver(key),
                "raw_value": values_by_key[key],
                "value": value_formatter(key, values_by_key[key]),
            }
            for key in sorted(values_by_key.keys())
            if key not in seen_keys and key not in excluded_keys
        ]
        if other_rows:
            sections.append(
                {
                    "title": other_title,
                    "description": other_description,
                    "rows": other_rows,
                }
            )

    return sections


def format_c14_integer(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return int(rounded)


def format_d13c(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return format(rounded, "f")


def format_one_decimal(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return format(rounded, "f")


def format_cn_ratio(value: Any) -> Any:
    if value is None:
        return None
    try:
        rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return value
    return format(rounded, "f")


def format_cn_ratio_from_conc(conc_c: Any, conc_n: Any) -> str | None:
    if conc_c is None or conc_n is None:
        return None
    try:
        c = Decimal(str(conc_c))
        n = Decimal(str(conc_n))
    except (InvalidOperation, ValueError):
        return None
    if n == 0:
        return None
    ratio = (c / Decimal("12.011")) / (n / Decimal("14.007"))
    return str(format_cn_ratio(ratio))


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
    (
        "Identity",
        "Personal and language details.",
        ("user_nr", "title", "salutation", "first_name", "last_name", "language"),
    ),
    (
        "Organisation",
        "Institution and billing settings.",
        ("organisation", "institute", "account", "invoice", "correspondance"),
    ),
    (
        "Contact",
        "Direct communication channels.",
        ("email", "phone_1", "phone_2", "fax", "www"),
    ),
    (
        "Address",
        "Postal address information.",
        ("address_1", "address_2", "town", "postcode", "country"),
    ),
    (
        "Notes",
        "Additional comments from the submitter record.",
        ("user_comment",),
    ),
)


def _user_field_kind(key: str) -> str:
    if key in {"invoice", "correspondance"}:
        return "boolean"
    if key == "email":
        return "email"
    if key == "www":
        return "url"
    return "text"


def _format_user_value(key: str, value: Any) -> Any:
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
    return _build_sections(
        user,
        field_labels=USER_FIELD_LABELS,
        section_specs=USER_SECTION_SPECS,
        kind_resolver=_user_field_kind,
        value_formatter=_format_user_value,
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
    (
        "Core",
        "Core project identity and classification.",
        (
            "project_nr",
            "project",
            "status",
            "priority",
            "project_type",
            "research",
            "report_type",
        ),
    ),
    (
        "User",
        "Assigned user and responsible staff.",
        ("user_nr", "invoice_nr", "advisor", "supervisor"),
    ),
    (
        "Timeline",
        "Planning and delivery dates.",
        ("in_date", "desired_date", "out_date", "invoice_date"),
    ),
    (
        "Commercial",
        "Billing and order metadata.",
        ("price", "invoice", "free_of_charge", "auftrags_nr", "order_nr", "letter"),
    ),
    (
        "Logistics",
        "Storage and return logistics.",
        (
            "sample_storage_loc",
            "return_to_sender",
            "returned_to_sender",
            "prep_return_to_sender",
            "prep_returned_to_sender",
        ),
    ),
    (
        "Reporting",
        "Output and notes tied to the project.",
        ("report",),
    ),
)

PROJECT_BOOLEAN_FIELDS = {
    "invoice",
    "free_of_charge",
    "return_to_sender",
    "returned_to_sender",
    "prep_return_to_sender",
    "prep_returned_to_sender",
}


def _project_field_kind(key: str) -> str:
    if key in PROJECT_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"project_comment", "report", "letter"}:
        return "multiline"
    if "date" in key or key in {"in_date", "out_date", "desired_date"}:
        return "date"
    return "text"


def _format_project_value(key: str, value: Any) -> Any:
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
    return _build_sections(
        project,
        field_labels=PROJECT_FIELD_LABELS,
        section_specs=PROJECT_SECTION_SPECS,
        kind_resolver=_project_field_kind,
        value_formatter=_format_project_value,
        include_other=False,
        other_title="Other",
        other_description="Additional fields available in this project record.",
    )


SAMPLE_FIELD_LABELS = {
    "sample_nr": "Sample #",
    "project_nr": "Project #",
    "project_in_date": "Project In Date",
    "project_desired_date": "Project Desired Date",
    "project_out_date": "Project Out Date",
    "user_label": "Sample Label",
    "user_label_nr": "Sample Label #",
    "type": "Type",
    "material": "Material",
    "fraction": "Fraction",
    "sampling_date": "Sampling Date",
    "photo": "Photo",
    "user_desc1": "Description 1",
    "user_desc2": "Description 2",
    "user_comment": "User Comment",
    "pre_sub_treat": "Pre-sub Treatment",
    "preparation": "Preparation",
    "editable": "Editable",
    "not_tobedated": "Not To Be Dated",
    "residue": "Residue",
    "lab_comment": "Lab Comment",
    "weight": "Weight",
    "c14_age": "C14 Age",
    "c14_age_sig": "C14 Sigma",
    "av_fm": "Average Fm",
    "av_fm_sig": "Average Fm Sigma",
    "av_dc13": "Average d13C",
    "av_dc13_sig": "Average d13C Sigma",
    "delta_r": "Delta R",
    "calib": "Calibration",
    "cal1s_min": "Cal 1s Min",
    "cal1s_max": "Cal 1s Max",
    "cal2s_min": "Cal 2s Min",
    "cal2s_max": "Cal 2s Max",
    "storage": "Storage",
    "s_storage_loc": "Sample Storage Location",
    "prep_storage_loc": "Prep Storage Location",
    "left_over": "Leftover",
    "s_no_leftover": "No Leftover",
    "ma_nr": "MA #",
    "old_info": "Old Info",
    "c_n_isotop_a": "CN Isotop A",
    "c_n_isotop_a_moved": "CN Isotop A Moved",
}

SAMPLE_SECTION_SPECS: tuple[SectionSpec, ...] = (
    (
        "Main Info",
        "Primary sample identity and core submission fields.",
        (
            "sample_nr",
            "project_nr",
            "photo",
            "type",
            "material",
            "fraction",
            "editable",
            "ma_nr",
        ),
    ),
    (
        "Dates",
        "Submission context and project timeline.",
        ("sampling_date",),
    ),
    (
        "Lab Workflow",
        "Preparation and laboratory workflow metadata.",
        ("not_tobedated", "pre_sub_treat", "preparation", "residue"),
    ),
    (
        "Measurements",
        "Measured values and calculated signal fields.",
        ("weight", "c14_age", "c14_age_sig", "av_fm", "av_fm_sig", "av_dc13", "av_dc13_sig", "delta_r", "calib"),
    ),
    (
        "Calibration",
        "Calibration ranges and limits.",
        ("cal1s_min", "cal1s_max", "cal2s_min", "cal2s_max"),
    ),
    (
        "Storage",
        "Current location and leftovers.",
        ("s_no_leftover", "s_storage_loc", "prep_storage_loc"),
    ),
)

SAMPLE_PROJECT_SUBMISSION_KEYS: tuple[str, ...] = ("in_date", "desired_date", "out_date")

SAMPLE_BOOLEAN_FIELDS = {
    "editable",
    "not_tobedated",
    "s_no_leftover",
    "c_n_isotop_a",
    "c_n_isotop_a_moved",
}
SAMPLE_EXCLUDED_FIELDS = {
    "old_info",
    "storage",
    "left_over",
    "user_comment",
    "lab_comment",
    "user_label",
    "user_label_nr",
    "user_desc1",
    "user_desc2",
}


def _sample_field_kind(key: str) -> str:
    if key in SAMPLE_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"user_comment", "lab_comment", "old_info", "user_desc1", "user_desc2"}:
        return "multiline"
    if "date" in key or key.endswith("_date"):
        return "date"
    return "text"


def format_sample_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if key in {"av_fm", "av_fm_sig", "av_dc13", "av_dc13_sig"}:
        try:
            rounded_4 = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return value
        return format(rounded_4, "f")
    if key in {"c14_age", "c14_age_sig"}:
        return format_c14_integer(value)
    if key in SAMPLE_BOOLEAN_FIELDS:
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


def build_sample_sections(sample: Any, project: Any | None = None) -> list[dict[str, Any]]:
    project_values = _mapped_values(project) if project is not None else {}

    def extra_rows(section_title: str) -> Iterable[Row]:
        if section_title != "Dates" or not project_values:
            return []
        return [
            {
                "key": f"project_{project_key}",
                "label": SAMPLE_FIELD_LABELS.get(
                    f"project_{project_key}",
                    f"Project {project_key.replace('_', ' ').title()}",
                ),
                "kind": "date",
                "raw_value": project_values.get(project_key),
                "value": format_sample_value(project_key, project_values.get(project_key)),
            }
            for project_key in SAMPLE_PROJECT_SUBMISSION_KEYS
        ]

    return _build_sections(
        sample,
        field_labels=SAMPLE_FIELD_LABELS,
        section_specs=SAMPLE_SECTION_SPECS,
        kind_resolver=_sample_field_kind,
        value_formatter=format_sample_value,
        include_other=True,
        other_title="Other Analysis",
        other_description="Additional fields available in this sample record.",
        other_excluded_keys=SAMPLE_EXCLUDED_FIELDS,
        extra_rows_by_section=extra_rows,
    )


PREPARATION_FIELD_LABELS = {
    "sample_nr": "Sample #",
    "prep_nr": "Prep #",
    "batch": "Batch",
    "prep_start": "Prep Start",
    "prep_end": "Prep End",
    "stop": "Discarded",
    "prep_comment": "Preparation Comment",
    "weight_start": "Weight Start",
    "weight_medium": "Weight Mid",
    "weight_medium_2": "Weight Mid 2",
    "weight_end": "Weight End",
    "p_no_leftover": "No Leftover",
    "cn_ratio": "CN Ratio",
    "c_percent": "C %",
    "n_percent": "N %",
    "yield_percent": "Yield (%)",
    "step1_method": "Step 1 Method",
    "step1_start": "Step 1 Start",
    "step1_end": "Step 1 End",
    "step2_method": "Step 2 Method",
    "step2_start": "Step 2 Start",
    "step2_end": "Step 2 End",
    "step3_method": "Step 3 Method",
    "step3_start": "Step 3 Start",
    "step3_end": "Step 3 End",
    "step4_method": "Step 4 Method",
    "step4_start": "Step 4 Start",
    "step4_end": "Step 4 End",
    "step5_method": "Step 5 Method",
    "step5_start": "Step 5 Start",
    "step5_end": "Step 5 End",
    "old_info": "Old Info",
}

PREPARATION_SECTION_SPECS: tuple[SectionSpec, ...] = (
    (
        "Main Info",
        "Preparation identity and current batch context.",
        ("sample_nr", "prep_nr", "batch", "stop", "p_no_leftover"),
    ),
    (
        "Weights and Methods",
        "Weight progression paired with step methods.",
        (
            "weight_start",
            "prep_start",
            "step1_method",
            "step2_method",
            "step3_method",
            "step4_method",
            "step5_method",
            "weight_medium",
            "weight_medium_2",
            "weight_end",
            "prep_end",
        ),
    ),
    (
        "Step Timeline",
        "Start and end timestamps for each preparation step.",
        (
            "step1_start",
            "step1_end",
            "step2_start",
            "step2_end",
            "step3_start",
            "step3_end",
            "step4_start",
            "step4_end",
            "step5_start",
            "step5_end",
        ),
    ),
    (
        "EA Data",
        "Elemental analyzer values and derived indicators.",
        (
            "c_percent",
            "n_percent",
            "cn_ratio",
        ),
    ),
    (
        "Comments",
        "Preparation comments and legacy notes.",
        ("prep_comment", "old_info"),
    ),
)

PREPARATION_BOOLEAN_FIELDS = {"stop", "p_no_leftover"}
PREPARATION_EXCLUDED_FIELDS = {"left_over"}


def _preparation_field_kind(key: str) -> str:
    if key in PREPARATION_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"prep_comment", "old_info"}:
        return "multiline"
    if key in {"prep_start", "prep_end"}:
        return "date"
    if key.startswith("step") and (key.endswith("_start") or key.endswith("_end")):
        return "date"
    return "text"


def _format_preparation_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if key in PREPARATION_BOOLEAN_FIELDS:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    if key == "cn_ratio":
        return format_cn_ratio(value)
    return value


def _calculate_preparation_yield(weight_start: Any, weight_end: Any) -> str | None:
    if weight_start is None or weight_end is None:
        return None
    try:
        start = Decimal(str(weight_start))
        end = Decimal(str(weight_end))
    except (InvalidOperation, ValueError):
        return None
    if start == 0:
        return None
    yield_percent = (end / start) * Decimal("100")
    rounded = yield_percent.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return format(rounded, "f")


def build_preparation_sections(preparation: Any) -> list[dict[str, Any]]:
    values_by_key = _mapped_values(preparation)

    def extra_rows(section_title: str) -> Iterable[Row]:
        if section_title != "Weights and Methods":
            return []
        return [
            {
                "key": "yield_percent",
                "label": PREPARATION_FIELD_LABELS["yield_percent"],
                "kind": "text",
                "raw_value": _calculate_preparation_yield(
                    values_by_key.get("weight_start"),
                    values_by_key.get("weight_end"),
                ),
                "value": _calculate_preparation_yield(
                    values_by_key.get("weight_start"),
                    values_by_key.get("weight_end"),
                ),
                "read_only": True,
            }
        ]

    sections = _build_sections(
        preparation,
        field_labels=PREPARATION_FIELD_LABELS,
        section_specs=PREPARATION_SECTION_SPECS,
        kind_resolver=_preparation_field_kind,
        value_formatter=_format_preparation_value,
        include_other=True,
        other_title="Other",
        other_description="Additional fields available in this preparation record.",
        other_excluded_keys=PREPARATION_EXCLUDED_FIELDS,
        extra_rows_by_section=extra_rows,
    )
    for section in sections:
        if section.get("title") != "Weights and Methods":
            continue
        for row in section.get("rows", []):
            key = row.get("key")
            if key == "step1_method":
                row["divider_before"] = True
            elif key == "step5_method":
                row["divider_after"] = True
        weight_end_index = next((idx for idx, row in enumerate(section.get("rows", [])) if row.get("key") == "weight_end"), None)
        yield_index = next((idx for idx, row in enumerate(section.get("rows", [])) if row.get("key") == "yield_percent"), None)
        if weight_end_index is not None and yield_index is not None and yield_index != weight_end_index + 1:
            yield_row = section["rows"].pop(yield_index)
            insert_at = weight_end_index + 1
            if yield_index < insert_at:
                insert_at -= 1
            section["rows"].insert(insert_at, yield_row)
    return sections


TARGET_FIELD_LABELS = {
    "sample_nr": "Sample #",
    "prep_nr": "Prep #",
    "target_nr": "Target #",
    "target_id": "Target ID",
    "graph_batch": "Graph Batch",
    "graph_date": "Graph Date",
    "graphitized": "Graphitized",
    "magazine": "Magazine",
    "position": "Position",
    "reactor_nr": "Reactor #",
    "co2_init": "CO2 Init",
    "co2_final": "CO2 Final",
    "hydro_init": "Hydrogen Init",
    "hydro_final": "Hydrogen Final",
    "react_time": "Reaction Time",
    "target_comment": "Target Comment",
    "target_pressed": "Target Pressed",
    "stop": "Discarded",
    "meas_comment": "Measurement Comment",
    "fm": "FM",
    "fm_sig": "FM Sigma",
    "dc13": "d13C",
    "dc13_sig": "d13C Sigma",
    "calcset": "Calcset",
    "c14_age": "C14 Age",
    "c14_age_sig": "C14 Sigma",
    "cal1s_min": "Cal 1s Min",
    "cal1s_max": "Cal 1s Max",
    "cal2s_min": "Cal 2s Min",
    "cal2s_max": "Cal 2s Max",
    "weight_combustion": "Weight Combustion",
    "weight": "Weight",
    "temp": "Temperature",
    "conc_c": "C (%)",
    "conc_n": "N (%)",
    "cn_ratio_calc": "C/N Ratio",
    "le_curr": "LE Current",
    "he_curr": "HE Current",
}

TARGET_SECTION_SPECS: tuple[SectionSpec, ...] = (
    (
        "Main Info",
        "Target identity and assignment context.",
        (
            "sample_nr",
            "prep_nr",
            "target_nr",
            "target_id",
            "stop",
        ),
    ),
    (
        "Graphitisation",
        "Graphitisation setup and execution metadata.",
        (
            "weight_combustion",
            "graph_batch",
            "reactor_nr",
            "co2_init",
            "co2_final",
            "hydro_init",
            "hydro_final",
            "react_time",
            "temp",
            "graphitized",
            "target_pressed",
        ),
    ),
    (
        "Results",
        "Final radiocarbon and stable isotope results.",
        (
            "magazine",
            "position",
            "le_curr",
            "he_curr",
            "calcset",
            "fm",
            "fm_sig",
            "dc13",
            "dc13_sig",
            "c14_age",
            "c14_age_sig",
        ),
    ),
    (
        "Calibration",
        "Calibration threshold windows and acceptance bands.",
        (
            "cal1s_min",
            "cal1s_max",
            "cal2s_min",
            "cal2s_max",
        ),
    ),
    (
        "Elemental Analyzer",
        "EA concentrations and current values.",
        ("conc_c", "conc_n"),
    ),
    (
        "Comments",
        "Target and measurement comments plus legacy notes.",
        ("target_comment", "meas_comment"),
    ),
)

TARGET_BOOLEAN_FIELDS = {"stop"}


def _target_field_kind(key: str) -> str:
    if key in TARGET_BOOLEAN_FIELDS:
        return "boolean"
    if key in {"target_comment", "meas_comment"}:
        return "multiline"
    if key in {"graphitized", "target_pressed"}:
        return "date"
    if key in {"graph_date"}:
        return "datetime"
    return "text"


def format_target_indicator(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in {"fm", "fm_sig"}:
        try:
            rounded_4 = Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, ValueError):
            return value
        return format(rounded_4, "f")
    if key in {"dc13", "dc13_sig"}:
        return format_d13c(value)
    if key in {"c14_age", "c14_age_sig"}:
        return format_c14_integer(value)
    return value


def _format_target_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return None
    if key in TARGET_BOOLEAN_FIELDS:
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return value
        if numeric == 1:
            return "Yes"
        if numeric == 0:
            return "No"
        return str(value)
    if key in {"conc_c", "conc_n"}:
        return format_one_decimal(value)
    if key in {"fm", "fm_sig", "dc13", "dc13_sig", "c14_age", "c14_age_sig"}:
        return format_target_indicator(key, value)
    return value


def build_target_sections(target: Any) -> list[dict[str, Any]]:
    values_by_key = _mapped_values(target)

    def extra_rows(section_title: str) -> Iterable[Row]:
        if section_title != "Elemental Analyzer":
            return []
        ratio = format_cn_ratio_from_conc(values_by_key.get("conc_c"), values_by_key.get("conc_n"))
        return [
            {
                "key": "cn_ratio_calc",
                "label": TARGET_FIELD_LABELS["cn_ratio_calc"],
                "kind": "text",
                "raw_value": ratio,
                "value": ratio,
                "read_only": True,
            }
        ]

    sections = _build_sections(
        target,
        field_labels=TARGET_FIELD_LABELS,
        section_specs=TARGET_SECTION_SPECS,
        kind_resolver=_target_field_kind,
        value_formatter=_format_target_value,
        include_other=False,
        extra_rows_by_section=extra_rows,
    )
    for section in sections:
        title = section.get("title")
        if title == "Graphitisation":
            for row in section.get("rows", []):
                key = row.get("key")
                if key == "reactor_nr":
                    row["divider_before"] = True
                elif key == "graphitized":
                    row["divider_before"] = True
        elif title == "Results":
            for row in section.get("rows", []):
                key = row.get("key")
                if key == "fm":
                    row["divider_before"] = True
    return sections

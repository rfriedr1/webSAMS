"""One label per field, for every page.

A database column is called the same thing wherever it shows up: a list
table's column head, a detail page's fact-sheet row, a bench field, the
import wizard. Before this registry the table heads
(`TABLE_HEADER_LABELS`) and each detail page (`SAMPLE_FIELD_LABELS`,
`PROJECT_FIELD_LABELS`, …) kept their own dictionaries, and 25 fields had
drifted apart ("User Label" in the project's sample table, "Sample Label"
on the sample page; "d13C" vs "δ¹³C"; "Cal 1s" vs "Cal 1σ").

Rules:
- Key = the column name (or the query alias a list uses). The same column
  name in two tables means the same thing (`stop` is "Discarded" on a
  preparation and on a target), so there are no per-entity overrides.
- Labels are Title Case (the lab's choice, 2026-11); short joining words
  stay lower case ("Free of Charge", "Return to Sender") and acronyms and
  symbols keep their case (FM, C14, δ¹³C, MA #, ID).
- A template never writes a field's label by hand: it calls
  `field_label(key)` (Jinja global, also `format_table_header_label`).
  `tests/test_field_labels.py` fails on a hand-written `<th>` that names a
  field, and on any model column missing from this registry.
"""

from __future__ import annotations

from typing import Any

FIELD_LABELS: dict[str, str] = {
    # ---- Identifiers ------------------------------------------------------
    "sample_nr": "Sample #",
    "project_nr": "Project #",
    "user_nr": "Submitter #",
    "prep_nr": "Prep #",
    "target_nr": "Target #",
    "target_id": "Target ID",
    "ma_nr": "MA #",
    "invoice_nr": "Invoice Recipient #",
    "auftrags_nr": "Order ID",
    "auftragsnr": "Order ID",
    "order_nr": "Order #",
    # ---- Submitter (user_t) -----------------------------------------------
    "salutation": "Salutation",
    "title": "Title",
    "first_name": "First Name",
    "last_name": "Last Name",
    "user_last_name": "Submitter",
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
    "email": "E-mail",
    "www": "Website",
    "account": "Account",
    "correspondance": "Correspondence",
    "language": "Language",
    "user_comment": "Submitter Comment",
    # ---- Project (project_t) ----------------------------------------------
    "project": "Project Name",
    "status": "Status",
    "priority": "Priority",
    "in_date": "In Date",
    "desired_date": "Desired Date",
    "out_date": "Out Date",
    "invoice": "Invoice",
    "invoice_date": "Invoice Date",
    "price": "Price",
    "free_of_charge": "Free of Charge",
    "project_type": "Project Type",
    "research": "Research",
    "report": "Report",
    "report_type": "Report Type",
    "letter": "Letter",
    "advisor": "Advisor",
    "supervisor": "Supervisor",
    "project_comment": "Project Comment",
    "sample_storage_loc": "Sample Storage Location",
    "return_to_sender": "Return to Sender",
    "returned_to_sender": "Returned to Sender",
    "prep_return_to_sender": "Prep Return to Sender",
    "prep_returned_to_sender": "Prep Returned to Sender",
    # The project's dates as shown on a sample page.
    "project_in_date": "Project In Date",
    "project_desired_date": "Project Desired Date",
    "project_out_date": "Project Out Date",
    # ---- Sample (sample_t) ------------------------------------------------
    "user_label": "Sample Label",
    "user_label_nr": "Sample Label #",
    "user_desc1": "Description 1",
    "user_desc2": "Description 2",
    "type": "Type",
    "material": "Material",
    "fraction": "Fraction",
    "weight": "Weight",
    "sampling_date": "Sampling Date",
    "pre_sub_treat": "Submitter Pre-treatment",
    "preparation": "Preparation",
    "residue": "Residue",
    "photo": "Photo",
    "editable": "Editable",
    "not_tobedated": "Not to Be Dated",
    "lab_comment": "Lab Comment",
    "old_info": "Old Info",
    "storage": "Storage",
    "s_storage_loc": "Sample Storage Location",
    "prep_storage_loc": "Prep Storage Location",
    "left_over": "Leftover",
    "s_no_leftover": "No Leftover",
    "p_no_leftover": "No Leftover",
    "c_n_isotop_a": "C/N Isotope Analysis",
    "c_n_isotop_a_moved": "Moved to C/N Analysis",
    "dendro_a": "Dendro Analysis",
    # ---- Results (sample and target) --------------------------------------
    "c14_age": "C14 Age",
    "c14_age_sig": "C14 Age Sigma",
    "fm": "FM",
    "fm_sig": "FM Sigma",
    "av_fm": "Average FM",
    "av_fm_sig": "Average FM Sigma",
    "dc13": "δ¹³C",
    "dc13_sig": "δ¹³C Sigma",
    "av_dc13": "Average δ¹³C",
    "av_dc13_sig": "Average δ¹³C Sigma",
    "delta_r": "Delta R",
    "calib": "Calibration",
    "calcset": "Calc Set",
    "cal1s_min": "Cal 1σ Min",
    "cal1s_max": "Cal 1σ Max",
    "cal2s_min": "Cal 2σ Min",
    "cal2s_max": "Cal 2σ Max",
    # ---- Preparation (preparation_t) --------------------------------------
    "batch": "Prep Batch",
    "prep_start": "Prep Start",
    "prep_end": "Prep End",
    "prep_comment": "Prep Comment",
    "stop": "Discarded",
    "weight_start": "Weight Start",
    "weight_medium": "Weight Mid",
    "weight_medium_2": "Weight Mid 2",
    "weight_end": "Weight End",
    "yield_percent": "Yield (%)",
    "cn_ratio": "C/N Ratio",
    "c_percent": "C (%)",
    "n_percent": "N (%)",
    **{
        f"step{n}_{part}": f"Step {n} {part.title()}"
        for n in range(1, 6)
        for part in ("method", "start", "end")
    },
    # ---- Target (target_t) ------------------------------------------------
    "magazine": "Magazine",
    "position": "Position",
    "graph_batch": "Graph Batch",
    "graph_date": "Graph Date",
    "graphitized": "Graphitized",
    "target_pressed": "Target Pressed",
    "target_comment": "Target Comment",
    "meas_comment": "Measurement Comment",
    "reactor_nr": "Reactor #",
    "cathode_nr": "Cathode #",
    "co2_init": "CO2 Init",
    "co2_final": "CO2 Final",
    "hydro_init": "Hydrogen Init",
    "hydro_final": "Hydrogen Final",
    "react_time": "Reaction Time",
    "temp": "Temperature",
    "precis": "Precision",
    "cycle_min": "Cycle Min",
    "cycle_max": "Cycle Max",
    "combustion": "Combustion",
    "catalyst": "Catalyst",
    "editallowed": "Edit Allowed",
    "weight_combustion": "Combustion Weight",
    "conc_c": "C (%)",
    "conc_n": "N (%)",
    "cn_ratio_calc": "C/N Ratio",
    "total_c_ug": "Total C (µg)",
    "le_curr": "LE Current",
    "he_curr": "HE Current",
    # ---- Computed list columns (query aliases) ----------------------------
    "days_in_prep": "Days in Prep",
    "days_to_deadline": "Days to Deadline",
    "in_freeze": "In Freeze",
    "samples": "Samples",
    "measured": "Measured",
}


def default_label(key: str) -> str:
    """Fallback for a key the registry does not know: `snake_case` →
    Title Case. A database column never needs it (the test checks every
    model column is registered); it covers ad-hoc query aliases."""
    return str(key).replace("_", " ").strip().title()


def field_label(key: Any) -> str:
    """The label for a field, the same on every page."""
    key_str = str(key)
    label = FIELD_LABELS.get(key_str) or FIELD_LABELS.get(key_str.lower())
    return label if label is not None else default_label(key_str)

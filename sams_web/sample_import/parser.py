"""Locate and interpret the submission sheet by content, not position.

Two independent detectors run over the grid:

1. `find_sample_table_header` scans every row and scores it by how many
   cells resolve to known sample-column names. The best-scoring row wins,
   which means the sample table can start at any row and its columns can
   appear in any order — reordering or inserting columns is a no-op.

2. `parse_metadata_block` walks the rows *above* that header as
   `label | value` pairs, tracking which section it is in (submitter vs
   invoice recipient) from the section headings it passes. Instructional
   helper text in neighbouring columns is filtered by `is_noise`, so an
   unfilled template correctly yields empty values rather than the word
   "required".

The legacy Delphi importer addressed cells by hard-coded index and broke
on any layout change; this one only breaks if a *label* becomes
unrecognisable, which the operator can then fix in the review UI.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from openpyxl.utils import get_column_letter

from sams_web.sample_import.draft import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    ColumnMapping,
    ContactDraft,
    ImportDraft,
    Issue,
    ProjectDraft,
    SampleDraft,
)
from sams_web.sample_import.workbook import Cell, Grid
from sams_web.sample_import.vocabulary import (
    CONTACT_LABEL_SYNONYMS,
    INVOICE_SECTION_MARKERS,
    PROJECT_LABEL_SYNONYMS,
    SAMPLE_COLUMN_SYNONYMS,
    SAMPLE_TABLE_SECTION_MARKERS,
    SAME_INVOICE_ADDRESS_MARKERS,
    SUBMITTER_SECTION_MARKERS,
    contains_marker,
    is_blank_equivalent,
    is_noise,
    parse_boolean,
    resolve_label,
)

#: Minimum number of recognised column headers for a row to be accepted
#: as the sample-table header. Two is enough to be decisive while still
#: tolerating a sheet that only carries name + material.
MIN_HEADER_MATCHES = 2

#: How many consecutive blank rows end the sample table. Generous,
#: because customers leave gaps between groups of samples.
BLANK_ROW_RUN_ENDS_TABLE = 25

#: How far above the sample table we look for metadata. The template
#: uses ~34 rows; this leaves room for extra blocks.
MAX_METADATA_ROWS = 200


def _cell_maps_to_sample_field(
    cell: Cell, synonyms: dict[str, tuple[str, ...]]
) -> tuple[str | None, float]:
    """Resolve a header cell, ignoring section headings like
    'Probenliste / sample list' which would otherwise be mistaken for a
    'sample name' column."""
    if cell.is_empty:
        return None, 0.0
    if contains_marker(cell.value, SAMPLE_TABLE_SECTION_MARKERS):
        return None, 0.0
    return resolve_label(cell.value, synonyms)


def find_sample_table_header(
    grid: Grid, *, synonyms: dict[str, tuple[str, ...]] | None = None
) -> tuple[int, list[ColumnMapping]]:
    """Return `(header_row, column_mappings)`; row 0 when not found.

    Scores every row by the number of distinct sample fields its cells
    resolve to. Ties break toward the earlier row, so a stray row of
    prose further down cannot steal the header.
    """
    synonyms = synonyms or SAMPLE_COLUMN_SYNONYMS
    best_row = 0
    best_score = 0.0
    best_columns: list[ColumnMapping] = []

    for row_index in range(1, grid.row_count + 1):
        cells = grid.row(row_index)
        if not cells:
            continue

        # field -> (confidence, ColumnMapping) keeping the best claim
        claimed: dict[str, tuple[float, ColumnMapping]] = {}
        unmapped: list[ColumnMapping] = []

        for cell in cells:
            field_name, confidence = _cell_maps_to_sample_field(cell, synonyms)
            mapping = ColumnMapping(
                column=cell.col,
                column_letter=get_column_letter(cell.col),
                header_text=cell.text,
                field_name=field_name,
                confidence=confidence,
            )
            if field_name is None:
                if not cell.is_empty:
                    unmapped.append(mapping)
                continue
            previous = claimed.get(field_name)
            if previous is None or confidence > previous[0]:
                # A column that loses its claim becomes an unmapped
                # column rather than vanishing, so the operator still
                # sees it in the review UI.
                if previous is not None:
                    demoted = previous[1]
                    demoted.field_name = None
                    demoted.confidence = 0.0
                    unmapped.append(demoted)
                claimed[field_name] = (confidence, mapping)
            else:
                mapping.field_name = None
                mapping.confidence = 0.0
                unmapped.append(mapping)

        if len(claimed) < MIN_HEADER_MATCHES:
            continue

        # Prefer rows with more matches, then higher average confidence.
        score = len(claimed) + sum(c for c, _ in claimed.values()) / 100.0
        if score > best_score:
            best_score = score
            best_row = row_index
            columns = [m for _, m in claimed.values()] + unmapped
            columns.sort(key=lambda m: m.column)
            best_columns = columns

    return best_row, best_columns


def _value_cell_for_label(grid: Grid, label_cell: Cell) -> Cell | None:
    """First cell to the right of `label_cell` that holds a real value.

    Skips empty cells and the template's instructional helper columns
    ('erforderlich / required', "enter 'n.a.' if not applicable"), which
    otherwise get picked up as the value on an unfilled template.
    """
    for col in range(label_cell.col + 1, grid.col_count + 1):
        cell = grid.cell(label_cell.row, col)
        if cell.is_empty:
            continue
        if is_noise(cell.value):
            continue
        return cell
    return None


def _clean_text(value: Any) -> str:
    """Collapse whitespace/newlines in a value cell to a single line."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return re.sub(r"\s+", " ", str(value)).strip()


def parse_metadata_block(
    grid: Grid, *, stop_row: int
) -> tuple[ContactDraft, ContactDraft, bool, ProjectDraft, list[Issue]]:
    """Parse the `label | value` rows above the sample table.

    Section tracking: a row whose first non-empty cell contains an
    invoice-section marker flips subsequent contact rows into the
    invoice block. The 'is this also the accounting address?' yes/no row
    is checked *first*, because it also contains the word
    'Rechnungsadresse' and would otherwise trigger the section switch a
    row early.
    """
    submitter = ContactDraft()
    invoice = ContactDraft()
    project = ProjectDraft()
    issues: list[Issue] = []
    same_invoice_address: bool | None = None

    section = "submitter"
    last_row = min(stop_row - 1 if stop_row else grid.row_count, MAX_METADATA_ROWS)

    for row_index in range(1, last_row + 1):
        cells = grid.row(row_index)
        label_cell = next((c for c in cells if not c.is_empty and not is_noise(c.value)), None)
        if label_cell is None:
            continue

        # --- 1. The accounting-address yes/no switch -------------------
        if contains_marker(label_cell.value, SAME_INVOICE_ADDRESS_MARKERS):
            value_cell = _value_cell_for_label(grid, label_cell)
            answer = parse_boolean(value_cell.value) if value_cell else None
            if answer is None:
                issues.append(
                    Issue(
                        severity=SEVERITY_INFO,
                        message=(
                            "Could not read the 'invoice address same as submitter?' "
                            "answer; assuming the submitter address is also used for billing."
                        ),
                        target="same_invoice_address",
                        cell=value_cell.address if value_cell else label_cell.address,
                    )
                )
            same_invoice_address = True if answer is None else answer
            continue

        # --- 2. Section switches --------------------------------------
        if contains_marker(label_cell.value, INVOICE_SECTION_MARKERS):
            section = "invoice"
            continue
        if contains_marker(label_cell.value, SUBMITTER_SECTION_MARKERS):
            section = "submitter"
            continue

        # --- 3. Project-level labels ----------------------------------
        project_field, _ = resolve_label(label_cell.value, PROJECT_LABEL_SYNONYMS)
        if project_field is not None:
            value_cell = _value_cell_for_label(grid, label_cell)
            if value_cell is not None and not is_blank_equivalent(value_cell.value):
                project.values[project_field] = _clean_text(value_cell.value)
                project.sources[project_field] = value_cell.address
            continue

        # --- 4. Contact labels, scoped to the current section ---------
        contact_field, _ = resolve_label(label_cell.value, CONTACT_LABEL_SYNONYMS)
        if contact_field is None:
            continue
        value_cell = _value_cell_for_label(grid, label_cell)
        if value_cell is None or is_blank_equivalent(value_cell.value):
            continue
        target = submitter if section == "submitter" else invoice
        # First occurrence wins: the submitter block precedes the
        # invoice block, and repeated labels within a block are a sheet
        # error we do not want to silently overwrite with.
        if contact_field not in target.values:
            target.values[contact_field] = _clean_text(value_cell.value)
            target.sources[contact_field] = value_cell.address

    # An empty invoice block means "bill the submitter" regardless of
    # what the yes/no cell said.
    if invoice.is_empty:
        same_invoice_address = True
    elif same_invoice_address is None:
        same_invoice_address = False

    return submitter, invoice, bool(same_invoice_address), project, issues


_NUMERIC_CHARS = re.compile(r"[^0-9.,\-]")


def parse_weight(value: Any) -> tuple[float | None, str | None]:
    """Parse a weight cell to milligrams.

    Returns `(weight, error_message)`. Tolerates unit suffixes ('4.2 mg'),
    comma decimal separators ('4,2'), and thousands separators, mirroring
    the legacy `ExtractNumber` helper but reporting failures instead of
    silently yielding 0.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        weight = float(value)
    else:
        cleaned = _NUMERIC_CHARS.sub("", str(value)).strip()
        if not cleaned:
            return None, f"Could not read a weight from {str(value).strip()!r}."
        # "1.234,5" -> European; "1,234.5" -> US; "4,2" -> European decimal
        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")
        try:
            weight = float(cleaned)
        except ValueError:
            return None, f"Could not read a weight from {str(value).strip()!r}."
    if weight < 0:
        return None, f"Weight {weight:g} is negative."
    return weight, None


def parse_sample_rows(
    grid: Grid, *, header_row: int, columns: list[ColumnMapping]
) -> list[SampleDraft]:
    """Read the data rows below the header into `SampleDraft`s.

    A row is a sample when its `user_label` cell has content. Rows with
    data but no label are kept with an error so the operator sees them
    rather than losing them silently; fully blank rows are skipped.
    """
    mapped = {c.column: c.field_name for c in columns if c.field_name}
    unmapped = {c.column: (c.header_text or c.column_letter) for c in columns if not c.field_name}
    label_columns = [col for col, f in mapped.items() if f == "user_label"]
    label_col = label_columns[0] if label_columns else None

    samples: list[SampleDraft] = []
    blank_run = 0

    for row_index in range(header_row + 1, grid.row_count + 1):
        if grid.row_is_empty(row_index):
            blank_run += 1
            if blank_run >= BLANK_ROW_RUN_ENDS_TABLE:
                break
            continue
        blank_run = 0

        values: dict[str, Any] = {}
        extras: dict[str, str] = {}
        issues: list[Issue] = []

        for col, field_name in mapped.items():
            cell = grid.cell(row_index, col)
            if cell.is_empty:
                continue
            if field_name == "weight":
                weight, error = parse_weight(cell.value)
                if error:
                    issues.append(
                        Issue(
                            severity=SEVERITY_WARNING,
                            message=error,
                            target="weight",
                            cell=cell.address,
                        )
                    )
                elif weight is not None:
                    values["weight"] = weight
                continue
            text = _clean_text(cell.value)
            if text:
                values[field_name] = text

        for col, header in unmapped.items():
            cell = grid.cell(row_index, col)
            if not cell.is_empty:
                extras[header] = _clean_text(cell.value)

        has_any = bool(values) or bool(extras)
        if not has_any:
            continue

        label = str(values.get("user_label", "")).strip()
        if not label:
            issues.append(
                Issue(
                    severity=SEVERITY_ERROR,
                    message="This row has data but no sample name.",
                    target="user_label",
                    cell=(
                        grid.cell(row_index, label_col).address
                        if label_col
                        else f"row {row_index}"
                    ),
                )
            )

        samples.append(
            SampleDraft(row_number=row_index, values=values, extras=extras, issues=issues)
        )

    return samples


def _flag_duplicate_labels(samples: list[SampleDraft]) -> None:
    """Warn on repeated sample names within the sheet.

    The lab uses the customer's own label as the working identifier, so
    duplicates make samples indistinguishable on the bench. Legacy did
    not check this at all during import; we warn rather than block,
    because occasionally a duplicate is intentional.
    """
    seen: dict[str, int] = {}
    for sample in samples:
        label = str(sample.values.get("user_label", "")).strip().lower()
        if not label:
            continue
        first_row = seen.get(label)
        if first_row is None:
            seen[label] = sample.row_number
            continue
        sample.issues.append(
            Issue(
                severity=SEVERITY_WARNING,
                message=f"Duplicate sample name — also used in row {first_row}.",
                target="user_label",
            )
        )


def parse_grid(
    grid: Grid,
    *,
    file_name: str,
    sample_synonyms: dict[str, tuple[str, ...]] | None = None,
) -> ImportDraft:
    """Turn one worksheet into an `ImportDraft`.

    `sample_synonyms` lets the caller pass the Setup-extended heading
    vocabulary (see `vocabulary.merge_synonyms`); omit it to use the
    built-in defaults only.
    """
    header_row, columns = find_sample_table_header(grid, synonyms=sample_synonyms)

    draft = ImportDraft(
        sheet_name=grid.sheet_name, file_name=file_name, header_row=header_row
    )

    if header_row == 0:
        draft.issues.append(
            Issue(
                severity=SEVERITY_ERROR,
                message=(
                    "No sample table found. The importer looks for a header row "
                    "containing at least two recognised columns such as "
                    "'sample name', 'material', 'weight' or 'comment'."
                ),
                target="samples",
            )
        )
        # Still parse the metadata so the operator sees what was read.
        submitter, invoice, same_invoice, project, issues = parse_metadata_block(
            grid, stop_row=0
        )
        draft.submitter, draft.invoice = submitter, invoice
        draft.same_invoice_address, draft.project = same_invoice, project
        draft.issues.extend(issues)
        return draft

    draft.columns = columns
    submitter, invoice, same_invoice, project, issues = parse_metadata_block(
        grid, stop_row=header_row
    )
    draft.submitter, draft.invoice = submitter, invoice
    draft.same_invoice_address, draft.project = same_invoice, project
    draft.issues.extend(issues)

    draft.samples = parse_sample_rows(grid, header_row=header_row, columns=columns)
    _flag_duplicate_labels(draft.samples)

    # --- draft-level validation ---------------------------------------
    if "user_label" not in draft.mapped_fields:
        draft.issues.append(
            Issue(
                severity=SEVERITY_ERROR,
                message=(
                    "No sample-name column was recognised. Map one of the columns "
                    "to 'Sample Label' below."
                ),
                target="columns",
            )
        )
    if not draft.samples:
        draft.issues.append(
            Issue(
                severity=SEVERITY_ERROR,
                message="The sample table is empty — no rows found below the header.",
                target="samples",
            )
        )
    if not project.values.get("project"):
        draft.issues.append(
            Issue(
                severity=SEVERITY_ERROR,
                message="No project name found. Enter one before importing.",
                target="project.project",
            )
        )
    if not submitter.values.get("last_name"):
        draft.issues.append(
            Issue(
                severity=SEVERITY_ERROR,
                message="No submitter last name found. Enter one before importing.",
                target="submitter.last_name",
            )
        )
    if not submitter.values.get("email"):
        draft.issues.append(
            Issue(
                severity=SEVERITY_WARNING,
                message=(
                    "No submitter e-mail found. Results are normally sent to this "
                    "address, so add one if you can."
                ),
                target="submitter.email",
            )
        )

    unmapped_with_data = sorted(
        {header for s in draft.samples for header in s.extras}
    )
    if unmapped_with_data:
        draft.issues.append(
            Issue(
                severity=SEVERITY_INFO,
                message=(
                    f"{len(unmapped_with_data)} extra column(s) contained data but "
                    "are not mapped to a sample field: "
                    + ", ".join(repr(h) for h in unmapped_with_data[:6])
                    + ("…" if len(unmapped_with_data) > 6 else "")
                    + ". Map them below or leave them out."
                ),
                target="columns",
            )
        )

    return draft


__all__ = [
    "find_sample_table_header",
    "parse_grid",
    "parse_metadata_block",
    "parse_sample_rows",
    "parse_weight",
]

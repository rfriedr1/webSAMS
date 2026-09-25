"""Flexible Excel-based sample submission import.

The lab receives filled-in copies of `Submit_Samples_Template.xlsx`. The
legacy Delphi importer read a CSV export of that sheet and addressed
cells by hard-coded row/column indices, so any inserted column or moved
block broke it silently.

This package parses the workbook by *content* instead:

- `vocabulary`  — synonym tables (German + English) mapping the many ways
                  a label can be written to a canonical field name.
- `workbook`    — reads any `.xlsx` into a normalized cell grid.
- `parser`      — locates the submitter/project metadata block and the
                  sample table by recognising labels, not positions.
- `draft`       — typed result objects handed to the review UI.
- `matching`    — existing-submitter lookup + lookup-table resolution.
- `commit`      — turns an approved draft into DB records.

The practical effect: columns may be reordered, renamed within reason,
or added, and rows may shift, without breaking the import.
"""

from __future__ import annotations

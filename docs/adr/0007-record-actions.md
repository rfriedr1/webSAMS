# Record actions: one-click changes across many records

Some lab tasks change the same field on many records. The trigger was C/N isotope analysis: when a whole project needs it, every sample had to be opened and ticked by hand. The same shape recurs (dendro analysis, no-leftover flags, return-to-sender on a customer's projects), so we add one mechanism rather than one button per case.

## Decisions

1. **An Actions menu on the record page.** Project and submitter pages carry an *Actions* button in the record header (next to where + Prep / + Target sit on other pages), shown only to users who may edit records. The menu is grouped by the kind of record written (Samples, Preparations, Projects), one row per field, each with a *Set* / *Clear* pair. The same actions appear in the command palette as *Action: …*.

2. **Ticked rows, or all.** The page's related table (a project's samples, a submitter's projects) gets a tick column. An action runs on the ticked rows, or on all rows when none are ticked. The head tick box ticks only the rows the table filter shows. A ticked number that does not belong to the record is refused (stale page or a tampered form), not skipped.

3. **Preview, then run.** Choosing an action opens a dialog listing what would change (record, label, old → new), how many records already have the value, warnings (e.g. clearing C/N on a sample already moved to C/N analysis) and records that cannot be changed. Only the dialog's primary button posts. The run re-reads the database; the preview only informs.

4. **Through the detail-page checks.** Every record is written with `apply_detail_update` and its entity's `DetailUpdateConfig`, via `SamsService.apply_many_and_commit` — read-only fields, dropdowns, required fields and post-rules hold exactly as on the record's own page. The preview runs the same checks and rolls back.

5. **Refused records are listed and left alone; the rest are committed together.** About 2 500 old samples (all ≤ 62388) lack a type, material or fraction, which the sample page requires. Making one of them block a whole project would make the action useless on old projects, and bypassing the checks would let actions write what the pages cannot. So the preview lists them with the reason, and the run changes the others in one commit.

6. **"Clear" means "not set".** An empty legacy value (NULL) counts as already cleared and is not rewritten to 0.

7. **Free-text fields are edited, not set.** A storage location is not one value for everyone: samples of one project sit in several boxes. So its action is *Edit* (with a *Clear* twin): the dialog lists every record in scope with its current value in an editable box, plus a *Fill all* field for the common case. Only changed rows are posted and checked; records the page would refuse are shown disabled with the reason. Decision 3 still holds — the editor *is* the preview: old values are visible, changed rows carry a dirty dot, and nothing is saved until the primary button. (Added 2026-11 for Sample / Prep Storage Location, project page only.)

8. **No run log, no undo (for now).** Every action has its opposite, which is the undo. Recording who ran what, with old values, belongs with the change log that comes with login (ADR-0006 §8); `apply_many_and_commit` is where it will hook in, next to `_apply_and_commit`.

## Consequences

- A new free-text action is one entry in `_TEXT_FIELDS` (`EditTextAction` + Clear).
- A new flag action is one entry in `_FLAGS` (`sams_web/record_actions.py`); its field must have a `FIELD_LABELS` entry and be writable in its config (`tests/test_record_actions.py` checks both). Work that is not "set field to value" (e.g. add a preparation to every sample) subclasses `RecordAction`.
- New write routes `POST /projects/{nr}/actions/{key}` and `/submitters/{nr}/actions/{key}` are guarded by *edit records*; their previews are guarded GETs returning JSON.
- "Record action" is the glossary term; avoid "batch", which already names three lab events.

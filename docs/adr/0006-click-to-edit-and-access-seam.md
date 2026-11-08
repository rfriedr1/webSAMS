# Click-to-edit detail pages, and one access seam for every write

Detail pages (sample, preparation, target, project, submitter) used to open read-only: the operator pressed **Edit** to switch the whole record into edit mode, or double-clicked one value for a single-field "quick edit" that saved at once. The lab found the switch cumbersome — most visits change one or two values, and the mode switch was an extra step every time. At the same time a login is coming (IIS + Windows Authentication, `docs/server_installation.md` §13), and with it users who may only view. Both touch the same code, so they were decided together.

## Decisions

1. **No edit mode.** An editable value opens in place when it is clicked or reached with Tab. A changed field stays open with its dirty dot; an unchanged one closes when focus leaves it. Esc reverts the open field.

2. **Batch save from one bar.** Changes pile up across fields. A sticky bar at the foot of the record appears only while something is unsaved: *Cancel* (ghost, left), *N unsaved changes*, *Save* (primary, right). Leaving the record with changes asks Discard / Save / Keep editing.

3. **Only changed fields are posted.** Before the form submits, every unchanged control is disabled, so the browser does not send it. `apply_detail_update` already treats a missing field as untouched and checks required fields against the stored values. The save route, the POST/redirect cycle and the 422 re-render are unchanged.

4. **Last save wins.** There is no conflict check against edits made by someone else since the page was opened. Because only changed fields travel, two people changing *different* fields of the same record no longer overwrite each other; two people changing the *same* field still do, silently. A per-field "changed since you opened the page" check was considered and deferred: it needs the original value posted alongside each change and a new error path, and the lab judged the risk low.

5. **A rejected save keeps the edits.** The re-rendered editors show the submitted values and carry `data-initial-value` = the stored value, so they are still dirty and Cancel goes back to what is in the database (before, Cancel after an error "reset" to the rejected input).

6. **One access seam, `sams_web/access.py`.** `Permission` (*edit records*, *manage setup*, *sign off QC*), `Role` (*viewer*, *editor*, *admin*) and `current_user(request)`. Every non-GET route carries `dependencies=guarded(Permission.X)`; `tests/test_access.py` fails on a write route without it. Templates hide write controls with `can("…")` and detail pages get `{name}_can_edit`, but the 403 from the guard is the real check.

7. **No login yet.** Until it exists every request is an anonymous user whose role is `SAMS_ACCESS_ROLE` (default `admin`, i.e. as before). With login, only `current_user()` changes: it will read the identity IIS forwards and look up the role.

8. **Change log deferred.** Recording who changed which field from what to what belongs with login, when there is a real "who". Every detail save already passes through `SamsService._apply_and_commit` with only the changed fields, which is where it will hook in.

## Consequences

- Single-click opening makes plain clicks on a value an edit gesture. Selecting text by dragging still works (a click that ends a selection does not open the field), and links inside a value (e-mail, website, related record) still navigate.
- The `e` shortcut and the Edit / View toggle are gone. `Ctrl/Cmd+S` saves only when something changed.
- View-only users see the same fact sheet with no pencils, no save bar and no *+ Prep* / *+ Target*; benches, import, Setup, EA check entry, void and sign-off hide their write controls the same way.

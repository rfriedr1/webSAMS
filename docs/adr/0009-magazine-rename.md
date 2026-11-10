# Renaming a magazine while it is being planned

A magazine is named after its measurement run (`MA261113` = instrument MA, 2026-11-13). While a magazine is planned, the run date often moves, and its name then says the wrong day. Until now the only fix was to rebuild it under the new name. Lab → Analysis now has an *Actions* menu in the Magazine panel with **Rename…** (2026-11).

## Where a magazine name lives

A magazine has no record of its own. Its name is written into:

| Table | Column | What it is |
|---|---|---|
| `measprog_t` | `magazine` (part of the key) | the planned measurement sequence, one row per position |
| `target_t` | `magazine` | each target's magazine |
| `magazine_t` | `name` (key) | the name list with `last_changed`. **Database triggers** on `measprog_t` and `target_t` (`*_insert_change`, `*_update_change`, `*_delete_change`) `REPLACE` the name into it whenever a row there changes; nothing ever removes a name. |
| `calc_set_t` | `magazine` | BATS' evaluation set of the magazine. Its key `calcset` is usually the magazine name too (`MA261104`, or `MB260928ST_1` for a second evaluation), and `calc_corr_t`, `calc_sample_t` and `target_t.calcset` refer to it. |

The views `magazine_p`, `target_p`, `target_v` and `target_calcset_p` read `target_t` and follow automatically.

## Decisions

1. **Only a magazine that was not measured can be renamed** (the lab's decision). It counts as measured when BATS has a calc set for it, or when any of its targets has a result (`fm`, `fm_sig`, `c14_age`, `c14_age_sig`, `dc13`, `le_curr`, `he_curr`), a `calcset` or is frozen (`editallowed = 2`). A measured magazine's name is also on the AMS and BATS computers (run files, calc set names), which this app cannot change. A rename after measurement would leave them pointing at nothing. The dialog still opens for a measured magazine and says why it is refused.

2. **Calc sets are therefore never touched.** An unmeasured magazine has none.

3. **The new name must be unused everywhere.** A name that any of the four tables already holds (upper and lower case count as the same, as in MySQL's collation) is refused: a rename never merges two magazines. A case-only change is refused as "the current name". The new name has at most 12 characters (`varchar(12)`), made of letters, digits, `-` and `_`.

4. **What is written, in one transaction** (`SamsRepository.rename_magazine`): `measprog_t.magazine` and `target_t.magazine`, then `magazine_t`. The triggers have by then added the new name to `magazine_t`, so the old row is deleted. A magazine with no sequence or target rows (planned, still empty) fires no trigger; its `magazine_t` row is renamed instead. The same rule works on a database without the triggers (the tests run on SQLite).

5. **Empty magazines are magazines.** The Magazine lookup used to find only names on `target_t`. A magazine still being planned may have no target yet, so the lookup and its list now also read `magazine_t`; such a magazine shows "No targets are assigned …" and can be renamed.

6. **Preview, then run.** As for record actions (ADR-0007) and the target swap (ADR-0008): opening the dialog loads a guarded GET (`/lab/analysis/magazine/rename/preview`) that lists what changes per table, or why the magazine is refused. *Check* (or Enter) validates the typed name; only a name the server accepted enables *Rename*, and typing again disables it until the next check. The POST (`/lab/analysis/magazine/rename`, *edit records*) checks everything again and redirects to the renamed magazine with an `action_notice` toast. The undo is renaming it back.

## Consequences

- `magazine_t`, `measprog_t` and (partly) `calc_set_t` are declared as Core tables in `models.py`, with `MAGAZINE_NAME_LENGTH = 12`.
- If magazine names ever appear in another table, add it to `magazine_usage`, `magazine_name_taken` and `rename_magazine`, and to the table above.
- The change log will hook into `SamsService.rename_magazine` once login exists (ADR-0006).

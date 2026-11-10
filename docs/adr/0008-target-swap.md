# Swapping the data of two mixed-up targets

Targets get mixed up: two tubes swapped on the graphitization rig, two cathodes swapped in the magazine, two rows swapped when typing. Afterwards the data stored on target A belongs to target B and the other way round. Until now the fix was retyping both targets by hand (and asking BATS to move its evaluation rows). The target page now has an *Actions* menu with **Swap target info** (2026-11).

## Decisions

1. **One target page, one other target.** The operator opens the action on target A and names target B by sample, prep and target number. Any other target qualifies; a target cannot be swapped with itself.

2. **Groups, ticked by default.** `target_t` columns are split into four groups (`SWAP_GROUPS` in `sams_web/target_swap.py`): *Graphitization*, *Elemental Analysis*, *Measurement and Results*, *Comments and Status*. The dialog shows both targets' values side by side per group (equal values muted, "N fields differ") and the operator unticks what should stay. A group whose values are equal on both targets would change nothing; it starts unticked and disabled (*nothing to swap*). A mix-up on the rig and a mix-up in the magazine move different groups, so this is the operator's call, not ours.

3. **Identity never moves.** Sample, prep and target number and `target_id` (`IDENTITY_FIELDS`) are what the target *is*. Every other `Target` column is in exactly one group; `tests/test_target_swap.py` fails on a new column that is not placed.

4. **The results move with BATS' evaluation rows.** Moving *Measurement and Results* also moves the two targets' `calc_sample_t` rows onto each other (the key is the primary key, so one side parks on `-1/-1/-1` for the duration of the transaction). Otherwise BATS' evaluation would describe the wrong target. Everything happens in one commit.

5. **An exception to ADR-0003, narrowly.** ADR-0003 says webSAMS never writes or recomputes BATS-owned fields. A swap writes them, but only by moving values that BATS produced from one target to the other; nothing is computed. That is the whole exception: the target page still cannot edit them, and `SamsService.swap_targets` is the only path (it bypasses `apply_detail_update` on purpose, because the target config marks those fields read-only).

6. **Frozen targets are allowed, with a warning.** About half the targets are frozen in BATS (`editallowed = 2`). Blocking them would make the action useless for the mix-ups found after evaluation, which are the usual case. The dialog says which target is frozen; the freeze state moves with the results.

7. **Sample averages are not touched.** `sample_t`'s averaged results (C14 age, FM …) were computed from the targets. The swap does not recompute them (ADR-0002/0003); the dialog says to re-evaluate both samples in BATS.

8. **Preview, then run.** Like record actions (ADR-0007): the dialog's comparison is a guarded GET returning JSON (`…/targets/{n}/swap/preview`); only the *Swap* button posts (`…/targets/{n}/swap`, guarded by *edit records*), the server reloads and checks both targets again, and the result comes back as an `action_notice` / `action_error` toast. The opposite of a swap is the same swap again; there is no run log until the change log comes with login (ADR-0006).

## Consequences

- A new `target_t` column must be put in a group or in `IDENTITY_FIELDS`.
- `calc_sample_t` is declared as a Core table in `models.py` (`calc_sample_table`), not a mapped class: webSAMS moves its rows but never edits them as records.
- `cal_curve` (in the database, not in the model before) was added to `Target` so a swap moves it with the other calibration outputs.

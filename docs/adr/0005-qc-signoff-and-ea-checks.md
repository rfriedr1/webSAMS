# EA checks and a generic QC sign-off, in webSAMS-owned tables

The daily **EA check** (a check standard — acetanilide today — combusted on each elemental analyzer, pass/fail against a window) moved from a paper log into webSAMS, and with it the supervisor's "check:" signature. Both are ISO/IEC 17025 records (§6.4.10 intermediate checks, §7.7 ensuring the validity of results, §7.5 technical records), so the design favours unalterable, self-explaining records over convenience.

## Decisions

1. **Three new tables, owned by webSAMS** (`ea_check_t`, `qc_signoff_t`, `qc_signoff_item_t`; DDL in `docs/sql/0005_qc_ea_checks.sql`). They live in the shared `db_dmams` but BATS does not read or write them. There is no migration tool, so they are created by hand; until they exist the pages report "not set up yet" (`SamsRepository.missing_qc_tables`) instead of failing.

2. **The sign-off is generic.** `qc_signoff_t` records *who signed which set, when, with what verdict and comment* for any `subject_type` (`ea_check` now; OXA2 scatter, blanks and IAEA standards are expected next). `subject_key` says what within the type (`ea1|acetanilide`). The statistics shown at review time are stored as `stats_json`, whose shape belongs to the subject type — so a new kind of review needs no new columns.

3. **Covered items are a link table, not a column.** `qc_signoff_item_t(signoff_id, item_type, item_ref)` lists exactly what was reviewed. A `signoff_id` column on the item would have been simpler for EA checks, but future items are rows in BATS-owned tables (`target_t`) that webSAMS must not alter. `UNIQUE (item_type, item_ref)` makes "signed at most once" a database guarantee, not just application logic. Only items up to the reviewed `period_to` are covered, so a check logged while the review dialog was open stays for the next sign-off.

4. **EA checks are standard-agnostic.** Instruments and check standards live in Setup (`ea_checks` section), not in tables. Each check row stores the standard's key, lot, reference values and pass window as they were when it was logged, so changing Setup never rewrites history, and statistics are always per (EA, standard). A new standard certifying C and/or N is a Setup entry. A standard certifying a new element (H, S) needs one additive `ALTER TABLE … ADD conc_s, s_ref, s_min, s_max` plus an entry in `ea_checks.ELEMENTS`. A row-per-element (EAV) design was rejected: harder to query, chart and export, for no present need.

5. **Records are never updated or deleted.** A mistyped check is *voided* (who, when, why) and stays visible, struck through and excluded from statistics. A check covered by a sign-off cannot be voided. A failed check is not a mistake — it is logged with a required comment (the corrective action) and normally followed by a re-run; several checks per day are expected, and an EA's status for the day is its latest non-voided attempt.

6. **Statistics are deliberately minimal**: n, n failed, workdays without a check, and per element mean, standard deviation, bias against the reference, the ±2s/±3s lines and points outside ±3s. Mean, s and bias use the *passed* checks only — a commented, re-run failure is a known nonconformity and would otherwise inflate s several times; failures are counted and listed separately.

## Known limit

There is no login yet, so `operator`, `voided_by` and `signed_by` are names picked from Setup → Lab Staff (`may_sign_off` marks supervisors). The record says who *claims* to have acted. When IIS with Windows Authentication arrives (server guide §13) these fields should be filled from the authenticated user instead, and the Lab Staff list reduced to the sign-off permission.

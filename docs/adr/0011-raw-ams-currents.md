# LE / HE currents from the raw AMS databases, through a definer procedure

Each AMS writes its raw measurement data into its own database on the same MariaDB server as `db_dmams`: **`db_dc14`** (AMS.03, magazines `MA…`) and **`db_ac14`** (AMS.38, magazines `MB…`). Their `workfinal` table holds the final row per target, with `ANA` (LE current) and `A` (HE current). The legacy SAMS copied these into `target_t.le_curr / he_curr` on its transfer step (`SAMS_Main.pas` ~7057–7145, rounded to 2 decimals). webSAMS now does this from Lab → Analysis: Magazine panel → *Actions* → *Fetch…* (2026-11).

## Decisions

1. **No second connection in the app.** The app keeps one database connection (`SAMS_DATABASE_URL`, `db_dmams`). The raw databases are on the same server, so `db_dmams` reads them by schema-qualified name.

2. **A stored procedure, not a view.** `ams_raw_currents(magazine)` (`docs/sql/0011_ams_raw_currents.sql`) returns, per target of the magazine, the currents of its newest raw row. A view would be simpler SQL, but a view that points to a missing database is invalid, and a mysqldump / HeidiSQL export of `db_dmams`, which is how the lab backs it up, stops on it (error 1356). A procedure is only checked when it is called. The lab required that **nothing breaks when the raw databases are unavailable**.

3. **`SQL SECURITY DEFINER`.** The procedure reads with the rights of the account that created it. The app's account needs `EXECUTE` on the procedure and nothing in `db_dc14` / `db_ac14`.

4. **The magazine prefix picks the AMS** (`AMS_RAW_SYSTEMS` in `repositories.py`, the same map as pyBATS' `AMS_SCHEMAS`): `MA` → `db_dc14`, `MB` → `db_ac14`. A call reads only that one database, so MA still works when `db_ac14` is gone and the other way round. Other prefixes are refused before any call.

5. **Newest row per target.** `workfinal` has no unique key on sample/prep/target (one duplicate in 21 392 rows when checked), so the procedure takes the highest `RECNO` and reports `raw_rows`; the preview says when there were several. Rows with an empty key are skipped. `workfinal` has no index on the target columns either; each call scans it once per magazine, which is fast at its size. An index there would be the AMS side's decision.

6. **Copied, not read live.** Pages show the stored `target_t` values. Only the action's preview and fetch touch the raw data (`SamsRepository.raw_currents_for_magazine` is the one call; `tests/test_raw_currents.py` fails if anything else uses it). The Analysis page does not even probe the raw databases when it loads.

7. **Never hangs, never a 500, never a partial change.** The call runs as `SET STATEMENT lock_wait_timeout=5, max_statement_time=15 FOR CALL …`. Any database error is rolled back and becomes a `RawDataError` with its MariaDB code; `raw_currents.describe_problem` says what happened and what to do (procedure missing, no EXECUTE, raw database / table / column missing, no rights, timeout or lock, server unreachable), always with "Nothing was changed". The preview answers HTTP 200 with `problem`; the fetch redirects with an `action_error` toast.

8. **Preview, then fetch.** As for record actions (ADR-0007), the swap (ADR-0008) and the rename (ADR-0009): the preview lists per target the stored and raw values and a status (*New*, *Replaces*, *Same*, *No raw data*). The fetch reads the raw data again and writes only new and differing values, in one transaction, through `SamsService.fetch_raw_currents` (where the change log will hook in). An empty or 0 raw value never overwrites or clears a stored one. Values equal to two decimals count as the same.

9. **Frozen targets are written too.** `editallowed = 2` protects BATS' results; the currents are raw values from the AMS, not BATS results. The preview counts them. This does not change ADR-0003: webSAMS still never writes the BATS-owned fields.

10. **The detail page keeps the currents read-only.** The fetch bypasses `apply_detail_update`, as the swap does, because the target's `DetailUpdateConfig` marks them read-only.

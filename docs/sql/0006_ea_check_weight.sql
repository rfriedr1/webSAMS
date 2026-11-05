-- Weight of the check standard weighed into the EA capsule, in mg.
-- Run once per database after 0005_qc_ea_checks.sql (db_dmams_test2, then
-- db_dmams). Until the column exists the EA check pages show
-- "not set up yet" and name the missing column.

ALTER TABLE ea_check_t
  ADD COLUMN weight_mg DECIMAL(7,3) NULL AFTER checked_at;   -- NULL = not entered

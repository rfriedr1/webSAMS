-- One-off fix (2026-11-09): samples listed in "To prep all" although their
-- project is closed / returned. Their preparation 1 was never started or
-- ended, which is all the queue looks at.
-- 90393 already has prep_end = 2026-11-09 (fixed by hand), so it is not here.

-- 1) Gas samples (no pretreatment): close preparation 1, the same way the
--    import closes a no-preparation sample (prep_end = midnight).
--    Expected: 3 rows affected.
UPDATE db_dmams.preparation_t
SET prep_end = '2026-11-09 00:00:00'
WHERE prep_nr = 1
  AND prep_end IS NULL
  AND prep_start IS NULL
  AND sample_nr IN (87318, 87322, 90397);

-- 2) Never prepared, project long returned (73564 wood, 84973 groundwater).
--    Not a gas sample, so "prep ended" would be untrue. Mark preparation 1
--    as Discarded instead. Expected: 2 rows affected.
UPDATE db_dmams.preparation_t
SET stop = 1
WHERE prep_nr = 1
  AND prep_end IS NULL
  AND prep_start IS NULL
  AND sample_nr IN (73564, 84973);

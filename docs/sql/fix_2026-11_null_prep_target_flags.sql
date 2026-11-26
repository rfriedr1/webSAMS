-- One-off fix (2026-11-09): preparations and targets created by the web
-- import before PR #65 had Discarded (stop) / No Leftover (p_no_leftover)
-- stored as NULL, which hides them from the lab queues (they filter stop = 0).
-- Expected: 175 preparation rows, 175 target rows (samples 92490-92715).
-- Only empty flags are touched; a flag already set is left as it is.

UPDATE db_dmams.preparation_t pr
JOIN db_dmams.sample_t s ON s.sample_nr = pr.sample_nr
JOIN db_dmams.project_t p ON p.project_nr = s.project_nr
SET pr.stop = COALESCE(pr.stop, 0),
    pr.p_no_leftover = COALESCE(pr.p_no_leftover, 0)
WHERE p.in_date >= '2026-11-05'
  AND (pr.stop IS NULL OR pr.p_no_leftover IS NULL);

UPDATE db_dmams.target_t t
JOIN db_dmams.sample_t s ON s.sample_nr = t.sample_nr
JOIN db_dmams.project_t p ON p.project_nr = s.project_nr
SET t.stop = 0
WHERE p.in_date >= '2026-11-05'
  AND t.stop IS NULL;

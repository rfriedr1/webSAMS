-- LE / HE currents from the raw AMS databases (ADR-0011).
-- Run once per database (db_dmams_test2, then db_dmams), as an account that
-- may SELECT in db_dc14 and db_ac14: it becomes the procedure's DEFINER, and
-- the procedure reads the raw databases with the definer's rights. The app's
-- own database user needs nothing in db_dc14 / db_ac14, only EXECUTE on this
-- procedure (the GRANT at the end).
--
-- Why a procedure and not a view: a view that points to a missing database is
-- invalid, and a mysqldump / HeidiSQL export of db_dmams stops on it (error
-- 1356). A procedure is only checked when it is called, so backups never
-- depend on the raw databases. When they are unavailable, only the "Fetch
-- LE/HE currents" action on Lab -> Analysis reports it; nothing else in the
-- app touches them.
--
-- One call returns, for every target of one magazine, the currents of that
-- target's newest row in the raw database of the magazine's AMS:
--   MA... -> db_dc14 (AMS.03)      MB... -> db_ac14 (AMS.38)
-- LE = ANA, HE = A, rounded to 2 decimals, as the legacy SAMS transfer did.
-- workfinal has no unique key on the target, so the newest row (highest
-- RECNO) is used and raw_rows says how many there were. Only the raw database
-- of the magazine's own AMS is read, so MA still works when db_ac14 is gone
-- and the other way round. Any other prefix returns no result set.
--
-- `target_t` is not qualified on purpose: in db_dmams_test2 the procedure
-- joins the test database's targets (the raw databases are only read).
--
-- DBeaver: run it with "Execute script" (Alt+X). HeidiSQL and the mysql
-- client understand the DELIMITER lines as written.

DELIMITER //

CREATE OR REPLACE PROCEDURE ams_raw_currents(IN p_magazine VARCHAR(12))
  READS SQL DATA
  SQL SECURITY DEFINER
  COMMENT 'webSAMS: LE/HE currents of one magazine from db_dc14 / db_ac14 (ADR-0011)'
BEGIN
  IF p_magazine LIKE 'MA%' THEN
    SELECT t.sample_nr, t.prep_nr, t.target_nr, l.n_rows AS raw_rows,
           ROUND(w.ANA, 2) AS le_curr, ROUND(w.A, 2) AS he_curr
      FROM target_t t
      JOIN (SELECT SAMPLE_NR, PREP_NR, TARGET_NR, MAX(RECNO) AS recno, COUNT(*) AS n_rows
              FROM db_dc14.workfinal
             WHERE SAMPLE_NR IS NOT NULL AND PREP_NR IS NOT NULL AND TARGET_NR IS NOT NULL
             GROUP BY SAMPLE_NR, PREP_NR, TARGET_NR) l
        ON l.SAMPLE_NR = t.sample_nr AND l.PREP_NR = t.prep_nr AND l.TARGET_NR = t.target_nr
      JOIN db_dc14.workfinal w ON w.RECNO = l.recno
     WHERE t.magazine = p_magazine;
  ELSEIF p_magazine LIKE 'MB%' THEN
    SELECT t.sample_nr, t.prep_nr, t.target_nr, l.n_rows AS raw_rows,
           ROUND(w.ANA, 2) AS le_curr, ROUND(w.A, 2) AS he_curr
      FROM target_t t
      JOIN (SELECT SAMPLE_NR, PREP_NR, TARGET_NR, MAX(RECNO) AS recno, COUNT(*) AS n_rows
              FROM db_ac14.workfinal
             WHERE SAMPLE_NR IS NOT NULL AND PREP_NR IS NOT NULL AND TARGET_NR IS NOT NULL
             GROUP BY SAMPLE_NR, PREP_NR, TARGET_NR) l
        ON l.SAMPLE_NR = t.sample_nr AND l.PREP_NR = t.prep_nr AND l.TARGET_NR = t.target_nr
      JOIN db_ac14.workfinal w ON w.RECNO = l.recno
     WHERE t.magazine = p_magazine;
  END IF;
END //

DELIMITER ;

-- The app's database user (the one in SAMS_DATABASE_URL) may run it. Replace
-- <app_user> and, in the test database, the schema name. Skip this when that
-- user already has EXECUTE on the whole database.
-- GRANT EXECUTE ON PROCEDURE db_dmams.ams_raw_currents TO '<app_user>'@'%';

-- Check (as the app user):  CALL ams_raw_currents('MB250101');
-- Remove:                   DROP PROCEDURE IF EXISTS ams_raw_currents;

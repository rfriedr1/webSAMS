-- EA checks and generic QC sign-off (ADR-0005).
-- Run once per database (db_dmams_test2, then db_dmams). webSAMS owns these
-- tables; BATS does not use them. Until they exist the EA Checks page and
-- the strip on Lab -> Graphitization show "not set up yet" instead of failing.

CREATE TABLE qc_signoff_t (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  subject_type  VARCHAR(30)  NOT NULL,   -- 'ea_check' now; later e.g. 'oxa2', 'blank', 'iaea_c7'
  subject_key   VARCHAR(40)  NOT NULL,   -- what within the type: 'ea1|acetanilide'
  period_from   DATETIME     NOT NULL,   -- first item covered
  period_to     DATETIME     NOT NULL,   -- last item covered
  n_items       INT          NOT NULL,
  n_flagged     INT          NOT NULL,   -- failed / out-of-limit items in the set
  stats_json    TEXT         NULL,       -- statistics snapshot as reviewed (shape owned by the type)
  verdict       VARCHAR(20)  NOT NULL,   -- 'accepted' | 'accepted_remarks' | 'rejected'
  signed_by     VARCHAR(40)  NOT NULL,
  signed_at     DATETIME     NOT NULL,
  comment       VARCHAR(500) NULL,
  KEY ix_qc_signoff_subject (subject_type, subject_key, signed_at)
);

CREATE TABLE qc_signoff_item_t (
  signoff_id    INT          NOT NULL,
  item_type     VARCHAR(30)  NOT NULL,   -- 'ea_check' now; later e.g. 'target'
  item_ref      VARCHAR(40)  NOT NULL,   -- id or natural key of the item ('123', '48211.1.1')
  PRIMARY KEY (signoff_id, item_type, item_ref),
  UNIQUE KEY ux_qc_item_once (item_type, item_ref),
  CONSTRAINT fk_qc_item_signoff FOREIGN KEY (signoff_id) REFERENCES qc_signoff_t (id)
);

CREATE TABLE ea_check_t (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  ea          VARCHAR(20)  NOT NULL,           -- instrument key from Setup, e.g. 'ea1'
  standard    VARCHAR(30)  NOT NULL,           -- check-standard key from Setup, e.g. 'acetanilide'
  rm_lot      VARCHAR(40)  NULL,               -- lot of that standard (traceability)
  checked_at  DATETIME     NOT NULL,
  conc_c      DECIMAL(6,3) NULL,               -- measured C %
  conc_n      DECIMAL(6,3) NULL,               -- measured N %
  c_ref DECIMAL(6,3) NULL, c_min DECIMAL(6,3) NULL, c_max DECIMAL(6,3) NULL,  -- snapshot
  n_ref DECIMAL(6,3) NULL, n_min DECIMAL(6,3) NULL, n_max DECIMAL(6,3) NULL,  -- snapshot
  passed      TINYINT(1)   NOT NULL,
  operator    VARCHAR(40)  NOT NULL,
  comment     VARCHAR(255) NULL,
  voided      TINYINT(1)   NOT NULL DEFAULT 0,
  void_reason VARCHAR(255) NULL,
  voided_by   VARCHAR(40)  NULL,
  voided_at   DATETIME     NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  KEY ix_ea_checked (ea, standard, checked_at)
);

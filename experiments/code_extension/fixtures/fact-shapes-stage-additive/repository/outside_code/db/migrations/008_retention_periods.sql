-- Days archived jobs are kept per project, keyed by the stored stage code.
CREATE TABLE IF NOT EXISTS stage_retention (
  project TEXT NOT NULL,
  stage_code INTEGER NOT NULL,
  days INTEGER NOT NULL CONSTRAINT retention_days CHECK (days BETWEEN 1 AND (CASE stage_code WHEN 3 THEN 3650 ELSE 365 END)),
  updated_by TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (project, stage_code)
);

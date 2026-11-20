-- Days archived jobs are kept per project, keyed by the stored stage code.
CREATE TABLE IF NOT EXISTS stage_retention (
  project TEXT NOT NULL,
  stage_code INTEGER NOT NULL,
  days INTEGER NOT NULL CONSTRAINT retention_days CHECK (days BETWEEN 1 AND 3650),
  updated_by TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  PRIMARY KEY (project, stage_code)
);

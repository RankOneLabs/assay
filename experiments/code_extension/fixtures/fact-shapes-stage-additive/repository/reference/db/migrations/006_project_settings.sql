CREATE TABLE IF NOT EXISTS project_settings (
  project TEXT PRIMARY KEY,
  wip_limit INTEGER NOT NULL CHECK (wip_limit BETWEEN 1 AND 1000),
  evidence_quota_bytes INTEGER NOT NULL CHECK (evidence_quota_bytes > 0),
  default_review_owner TEXT,
  stale_after_days INTEGER NOT NULL CHECK (stale_after_days BETWEEN 1 AND 3650),
  revision INTEGER NOT NULL CHECK (revision > 0),
  updated_by TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS project_settings_history (
  project TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  actor TEXT NOT NULL,
  changes TEXT NOT NULL,
  reason TEXT,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (project, revision)
);

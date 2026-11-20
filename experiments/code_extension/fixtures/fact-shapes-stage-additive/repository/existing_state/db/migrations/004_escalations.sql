CREATE TABLE IF NOT EXISTS escalation_rules (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  stage TEXT NOT NULL,
  max_age_minutes INTEGER NOT NULL CHECK (max_age_minutes BETWEEN 1 AND 525600),
  min_priority INTEGER NOT NULL CHECK (min_priority BETWEEN 0 AND 100),
  target TEXT NOT NULL,
  enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_by TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS escalation_rules_project ON escalation_rules(project, stage, id);

CREATE TABLE IF NOT EXISTS escalations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_id TEXT NOT NULL REFERENCES escalation_rules(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  project TEXT NOT NULL,
  stage TEXT NOT NULL,
  target TEXT NOT NULL,
  age_minutes INTEGER NOT NULL CHECK (age_minutes >= 0),
  opened_at INTEGER NOT NULL,
  acknowledged_by TEXT,
  acknowledged_at INTEGER,
  resolved_by TEXT,
  resolved_at INTEGER,
  resolution TEXT,
  CHECK ((acknowledged_by IS NULL) = (acknowledged_at IS NULL)),
  CHECK ((resolved_by IS NULL) = (resolved_at IS NULL))
);
-- One open escalation per job and rule; resolved ones remain as history.
CREATE UNIQUE INDEX IF NOT EXISTS escalations_open_once ON escalations(job_id, rule_id) WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS escalations_project ON escalations(project, resolved_at, opened_at, id);

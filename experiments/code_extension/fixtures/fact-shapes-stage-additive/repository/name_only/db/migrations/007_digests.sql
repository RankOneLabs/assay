CREATE TABLE IF NOT EXISTS digest_schedules (
  id TEXT PRIMARY KEY,
  principal TEXT NOT NULL,
  project TEXT NOT NULL,
  cadence TEXT NOT NULL CHECK (cadence IN ('daily', 'weekly')),
  weekday INTEGER CHECK (weekday BETWEEN 0 AND 6),
  hour INTEGER NOT NULL CHECK (hour BETWEEN 0 AND 23),
  utc_offset_minutes INTEGER NOT NULL CHECK (utc_offset_minutes BETWEEN -720 AND 840),
  enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
  revision INTEGER NOT NULL CHECK (revision > 0),
  next_run_at INTEGER NOT NULL,
  last_run_at INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  CHECK ((cadence = 'weekly') = (weekday IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS digest_schedules_owner ON digest_schedules(project, principal, id);
CREATE INDEX IF NOT EXISTS digest_schedules_due ON digest_schedules(project, enabled, next_run_at, id);

CREATE TABLE IF NOT EXISTS digests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schedule_id TEXT NOT NULL REFERENCES digest_schedules(id),
  principal TEXT NOT NULL,
  project TEXT NOT NULL,
  period_start INTEGER NOT NULL,
  period_end INTEGER NOT NULL CHECK (period_end > period_start),
  content TEXT NOT NULL,
  checksum TEXT NOT NULL,
  generated_by TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS digests_owner ON digests(project, principal, period_end, id);

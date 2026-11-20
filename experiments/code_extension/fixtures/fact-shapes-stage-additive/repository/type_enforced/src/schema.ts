/** Business tables refer to the migrated vocabulary tables; they do not redeclare vocabularies. */
export const businessSchema = `
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  description TEXT NOT NULL,
  stage TEXT NOT NULL,
  priority INTEGER NOT NULL CHECK (priority BETWEEN 0 AND 100),
  owner TEXT NOT NULL,
  project TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  archived_at INTEGER
);
CREATE INDEX IF NOT EXISTS jobs_project_stage ON jobs(project, stage, created_at, id);
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, archived_at);
CREATE TABLE IF NOT EXISTS evidence (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  kind TEXT NOT NULL REFERENCES evidence_kind_values(value),
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  checksum TEXT NOT NULL,
  author TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE(job_id, checksum)
);
CREATE INDEX IF NOT EXISTS evidence_job_kind ON evidence(job_id, kind, created_at, id);
CREATE TABLE IF NOT EXISTS grants (
  principal TEXT NOT NULL,
  permission TEXT NOT NULL REFERENCES route_permission_values(value),
  project TEXT NOT NULL,
  granted_by TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (principal, permission, project)
);
CREATE TABLE IF NOT EXISTS job_events (
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  actor TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS events_job ON job_events(job_id, sequence);
CREATE INDEX IF NOT EXISTS events_actor_time ON job_events(actor, created_at, sequence);
CREATE INDEX IF NOT EXISTS events_action ON job_events(action, sequence);
CREATE INDEX IF NOT EXISTS events_time ON job_events(created_at, sequence);
CREATE TABLE IF NOT EXISTS attempts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  session_id TEXT NOT NULL UNIQUE,
  worker TEXT NOT NULL,
  started_at INTEGER NOT NULL,
  finished_at INTEGER,
  exit_code INTEGER CHECK (exit_code BETWEEN 0 AND 255),
  output TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_dependencies (
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  requires_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
  actor TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (job_id, requires_id),
  CHECK (job_id != requires_id)
);
CREATE INDEX IF NOT EXISTS attempts_job ON attempts(job_id, started_at, id);
`;

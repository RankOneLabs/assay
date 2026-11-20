CREATE TABLE IF NOT EXISTS job_tags (
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  tag TEXT NOT NULL CHECK (length(tag) BETWEEN 1 AND 40),
  added_by TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (job_id, tag)
);
CREATE INDEX IF NOT EXISTS job_tags_tag ON job_tags(tag, job_id);

CREATE TABLE IF NOT EXISTS saved_searches (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  owner TEXT NOT NULL,
  name TEXT NOT NULL,
  query TEXT NOT NULL,
  shared INTEGER NOT NULL CHECK (shared IN (0, 1)),
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS saved_searches_visible ON saved_searches(project, shared, owner, name, id);

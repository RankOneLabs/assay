CREATE TABLE IF NOT EXISTS job_comments (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  parent_id TEXT REFERENCES job_comments(id) ON DELETE CASCADE,
  depth INTEGER NOT NULL CHECK (depth >= 0),
  author TEXT NOT NULL,
  body TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  deleted_at INTEGER,
  deleted_by TEXT,
  CHECK (parent_id IS NULL OR parent_id != id)
);
CREATE INDEX IF NOT EXISTS job_comments_job ON job_comments(job_id, created_at, id);
CREATE INDEX IF NOT EXISTS job_comments_parent ON job_comments(parent_id);

-- Each body a comment held before an edit, with the time it was written; the current
-- body stays on job_comments.
CREATE TABLE IF NOT EXISTS job_comment_revisions (
  comment_id TEXT NOT NULL REFERENCES job_comments(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL CHECK (revision > 0),
  body TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (comment_id, revision)
);

-- One row per principal named in a live comment, with that principal's read marker.
CREATE TABLE IF NOT EXISTS comment_mentions (
  comment_id TEXT NOT NULL REFERENCES job_comments(id) ON DELETE CASCADE,
  principal TEXT NOT NULL,
  project TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  read_at INTEGER,
  PRIMARY KEY (comment_id, principal)
);
CREATE INDEX IF NOT EXISTS comment_mentions_inbox ON comment_mentions(project, principal, read_at, created_at);

-- Runs group jobs that are followed as one. The roll-up engine stores a run's state as
-- JSON; status is a column so runs can be listed and indexed by it.
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  title TEXT NOT NULL,
  state TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'finished')),
  finished_at INTEGER,
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS runs_project_status ON runs(project, status, created_at, id);

-- Keep the status column in step with the stored state.
CREATE TRIGGER IF NOT EXISTS runs_status_column AFTER UPDATE OF state ON runs
WHEN json_extract(NEW.state, '$.total') > 0 AND json_extract(NEW.state, '$.done') = json_extract(NEW.state, '$.total')
BEGIN
  UPDATE runs SET status = 'finished' WHERE id = NEW.id;
END;

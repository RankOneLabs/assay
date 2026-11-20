-- Stored run summaries: building one reads every attempt of every job in the run.
CREATE TABLE IF NOT EXISTS run_summaries (
  run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  summary TEXT NOT NULL,
  stored_at INTEGER NOT NULL
);

CREATE TABLE stage_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CHECK (value IN (
    'queued',
    'active',
    'complete'
  ))
);

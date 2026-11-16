CREATE TABLE stage_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL CHECK (value IN ('queued', 'active', 'complete'))
);

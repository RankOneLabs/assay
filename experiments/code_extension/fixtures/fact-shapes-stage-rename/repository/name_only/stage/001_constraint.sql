CREATE TABLE stage_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CHECK (length(value) > 0)
);

CREATE TABLE evidence_kind_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CHECK (length(value) > 0)
);
CREATE TABLE evidence_kind_capabilities (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CHECK (value IN ('document'))
);

CREATE TABLE stage_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CONSTRAINT stage_value_check CHECK (value IN ('queued', 'active', 'complete'))
);

CREATE TABLE evidence_kind_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CONSTRAINT evidence_kind_value_check CHECK (length(value) > 0)
);

CREATE TABLE route_permission_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CONSTRAINT route_permission_value_check CHECK (length(value) > 0)
);

CREATE TABLE route_permission_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL CHECK (value IN ('case_read', 'case_write', 'case_admin'))
);

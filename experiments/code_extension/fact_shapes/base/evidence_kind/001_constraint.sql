CREATE TABLE evidence_kind_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL CHECK (value IN ('document', 'image', 'testimony'))
);

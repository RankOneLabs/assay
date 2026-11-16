CREATE TABLE evidence_kind_values (
  id TEXT PRIMARY KEY,
  value TEXT NOT NULL UNIQUE CHECK (value IN (
    'document',
    'image',
    'testimony'
  ))
);

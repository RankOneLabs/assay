-- Notification subscriptions, webhook endpoints, and the outbox that feeds both from job_events.
CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  principal TEXT NOT NULL,
  pattern TEXT NOT NULL,
  job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
  stage TEXT,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS subscriptions_principal ON subscriptions(project, principal, id);

CREATE TABLE IF NOT EXISTS webhook_endpoints (
  id TEXT PRIMARY KEY,
  project TEXT NOT NULL,
  url TEXT NOT NULL,
  secret TEXT NOT NULL,
  active INTEGER NOT NULL CHECK (active IN (0, 1)),
  revision INTEGER NOT NULL CHECK (revision > 0),
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (project, url)
);

-- The last job_events sequence a project's collection pass has fanned out.
CREATE TABLE IF NOT EXISTS outbox_cursors (
  project TEXT PRIMARY KEY,
  sequence INTEGER NOT NULL CHECK (sequence >= 0),
  collected_by TEXT NOT NULL,
  updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL,
  principal TEXT NOT NULL,
  subscription_id TEXT REFERENCES subscriptions(id) ON DELETE SET NULL,
  event_sequence INTEGER NOT NULL,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  payload TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  read_at INTEGER,
  UNIQUE (project, principal, event_sequence)
);
CREATE INDEX IF NOT EXISTS notifications_inbox ON notifications(project, principal, read_at, id);

CREATE TABLE IF NOT EXISTS webhook_deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project TEXT NOT NULL,
  webhook_id TEXT NOT NULL REFERENCES webhook_endpoints(id) ON DELETE CASCADE,
  event_sequence INTEGER NOT NULL,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  action TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'dead')),
  attempts INTEGER NOT NULL CHECK (attempts >= 0),
  next_attempt_at INTEGER NOT NULL,
  lease_owner TEXT,
  lease_token TEXT,
  lease_expires_at INTEGER,
  last_status INTEGER,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  UNIQUE (webhook_id, event_sequence)
);
CREATE INDEX IF NOT EXISTS deliveries_due ON webhook_deliveries(project, status, next_attempt_at, id);

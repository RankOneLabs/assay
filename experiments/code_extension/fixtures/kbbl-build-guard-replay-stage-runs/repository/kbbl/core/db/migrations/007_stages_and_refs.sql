CREATE TABLE stages (
  name TEXT PRIMARY KEY,
  prompt_template_path TEXT NOT NULL,
  input_artifact_type TEXT NOT NULL CHECK (input_artifact_type IN ('spec','cohort','brief')),
  output_artifact_type TEXT NOT NULL CHECK (output_artifact_type IN ('plan','brief','pr')),
  gate TEXT NOT NULL CHECK (gate IN ('review_required','none')),
  default_backend TEXT NOT NULL
);

-- One row per stage dispatch: the stage, the artifact it ran on, and its session.
CREATE TABLE stage_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stage TEXT NOT NULL REFERENCES stages(name),
  input_artifact_type TEXT NOT NULL
    CHECK (input_artifact_type IN ('spec','cohort','brief')),
  input_artifact_id TEXT NOT NULL,
  session_ref TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX stage_runs_by_input ON stage_runs (stage, input_artifact_id);
ALTER TABLE briefs ADD COLUMN pr_url TEXT;

import type { Database } from "bun:sqlite";

/** One dispatch of a stage: the stage, the artifact it ran on, and its session. */
export interface StageRun {
  id: number;
  stage: string;
  input_artifact_type: "spec" | "cohort" | "brief";
  input_artifact_id: string;
  session_ref: string;
  created_at: string;
}

export function recordStageRun(
  db: Database,
  run: Pick<StageRun, "stage" | "input_artifact_type" | "input_artifact_id" | "session_ref">,
): StageRun {
  return db
    .prepare<StageRun, [string, string, string, string]>(
      `INSERT INTO stage_runs (stage, input_artifact_type, input_artifact_id, session_ref)
       VALUES (?, ?, ?, ?) RETURNING *`,
    )
    .get(run.stage, run.input_artifact_type, run.input_artifact_id, run.session_ref)!;
}

/** A stage's runs on one input artifact, newest first. */
export function listStageRuns(db: Database, stage: string, input_artifact_id: string): StageRun[] {
  return db
    .prepare<StageRun, [string, string]>(
      "SELECT * FROM stage_runs WHERE stage = ? AND input_artifact_id = ? ORDER BY id DESC",
    )
    .all(stage, input_artifact_id);
}

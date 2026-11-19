import * as stageTypes from "../../stage/types.ts";
import type { Job } from "../domain/models.ts";
/**
 * Stages whose jobs are exported from their current stored row. A job in any
 * other stage is exported as it was when it was first exported.
 */
const liveExportStages: readonly string[] = ["queued", "active", "complete"];
function exportedLive(stage: stageTypes.Stage): boolean {
  return liveExportStages.includes(stage);
}
export class ExportSnapshots {
  private readonly snapshots = new Map<string, Job>();
  read(job: Job): Job {
    if (exportedLive(job.stage)) return job;
    const kept = this.snapshots.get(job.id) ?? job;
    this.snapshots.set(job.id, kept);
    return kept;
  }
}

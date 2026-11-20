import * as stageTypes from "../../stage/types.ts";
import type { Job } from "../domain/models.ts";
/**
 * Open work is exported from its current stored row. A job in any other stage
 * no longer changes, so it is exported as it was when it was first exported.
 */
const exportedLive = (stage: stageTypes.Stage): boolean => stageTypes.stageTraits[stage].open;
export class ExportSnapshots {
  private readonly snapshots = new Map<string, Job>();
  read(job: Job): Job {
    if (exportedLive(job.stage)) return job;
    const kept = this.snapshots.get(job.id) ?? job;
    this.snapshots.set(job.id, kept);
    return kept;
  }
}

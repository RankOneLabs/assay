import type { Attempt, Job, JobRollup, RunRollup } from "../domain/models.ts";
import { isDoneWork, isOpenWork } from "../domain/progress.ts";
import { rollup } from "./engine.ts";
import { all, any, count, latest, when } from "./pieces.ts";

const unfinished = (attempt: Attempt): boolean => attempt.finishedAt === null;
const result = (attempt: Attempt): "passed" | "failed" => (attempt.exitCode === 0 ? "passed" : "failed");

/** A job over its attempts. */
export const jobRollup = rollup<Attempt, JobRollup>({
  attempts: count(),
  running: any(unfinished),
  outcome: latest(attempt => attempt.finishedAt, result),
});

/** A run over its jobs. */
export const runRollup = rollup<Job, RunRollup>({
  total: count(),
  open: count(job => isOpenWork(job.stage)),
  done: count(job => isDoneWork(job.stage)),
  status: when(all(job => isDoneWork(job.stage)), "finished", "running"),
});

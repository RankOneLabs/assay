export const values = ["queued", "active", "complete"] as const;
export type Stage = (typeof values)[number];
export function isValue(value: string): value is Stage {
  return (values as readonly string[]).includes(value);
}

/** How a job in a stage counts toward the run that contains it. */
export type Progress = "open" | "done";

/** How the service treats jobs in a stage. Every stage declares every trait. */
export interface StageTraits {
  /** Heading for the stage in reports and digests. */
  heading: string;
  /** Whether a job's details (priority, owner, evidence) can still change. */
  open: boolean;
  /** How the stage counts toward its run. */
  progress: Progress;
  /** Board path for the stage. */
  route: string;
  /** Stages a job can be moved to from this one. */
  next: readonly Stage[];
}

export const stageTraits: Record<Stage, StageTraits> = {
  queued: { heading: "Waiting", open: true, progress: "open", route: "/jobs/queue", next: ["active"] },
  active: { heading: "In progress", open: true, progress: "open", route: "/jobs/work", next: ["queued", "complete"] },
  complete: { heading: "Done", open: false, progress: "done", route: "/jobs/archive", next: [] },
};

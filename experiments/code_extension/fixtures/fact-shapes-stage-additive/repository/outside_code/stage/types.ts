export const values = ["queued", "active", "complete"] as const;
export type Stage = (typeof values)[number];
export function isValue(value: string): value is Stage {
  return (values as readonly string[]).includes(value);
}

/** How the service treats jobs in a stage. Every stage declares every trait. */
export interface StageTraits {
  /** Heading for the stage in reports and digests. */
  heading: string;
  /** Open work: details can change, it may escalate, it moves in bulk, exports read it live. */
  open: boolean;
  /** Stable number stored for the stage in settings tables. */
  code: number;
  /** Most days an archived job of this stage may be kept. */
  retentionDays: number;
  /** Board path for the stage. */
  route: string;
  /** Stages a job can be moved to from this one. */
  next: readonly Stage[];
}

export const stageTraits: Record<Stage, StageTraits> = {
  queued: { heading: "Waiting", open: true, code: 1, retentionDays: 365, route: "/jobs/queue", next: ["active"] },
  active: { heading: "In progress", open: true, code: 2, retentionDays: 365, route: "/jobs/work", next: ["queued", "complete"] },
  complete: { heading: "Done", open: false, code: 3, retentionDays: 3650, route: "/jobs/archive", next: [] },
};

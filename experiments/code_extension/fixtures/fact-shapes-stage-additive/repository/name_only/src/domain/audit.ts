import { z } from "zod";
import { values as stages } from "../../stage/types.ts";
import { keySchema, stageSchema } from "./validation.ts";
import { stageLabel } from "../presentation/labels.ts";
import type { Job, JobEvent } from "./models.ts";

const maxAuditPage = 200;
const maxAuditExport = 5000;

const timestamp = z.coerce.number().int().min(0).max(Number.MAX_SAFE_INTEGER);

const filterFields = z.object({
  actor: keySchema.optional(),
  // Actions are dotted lower-case names such as "job.transitioned"; a prefix like "comment." selects a family.
  action: z.string().regex(/^[a-z][a-z0-9_.]{0,79}$/).optional(),
  jobId: keySchema.optional(),
  from: timestamp.optional(),
  to: timestamp.optional(),
});

function ordered(filter: { from?: number; to?: number }): boolean {
  return filter.from === undefined || filter.to === undefined || filter.from < filter.to;
}
const rangeMessage = { message: "from must be earlier than to", path: ["from"] };

export type AuditFilter = z.infer<typeof filterFields>;

export const auditPageSchema = filterFields.extend({
  after: timestamp.default(0),
  limit: z.coerce.number().int().min(1).max(maxAuditPage).default(50),
}).strict().refine(ordered, rangeMessage);

export const auditExportSchema = filterFields.extend({
  after: timestamp.default(0),
  limit: z.coerce.number().int().min(1).max(maxAuditExport).default(1000),
}).strict().refine(ordered, rangeMessage);

const auditDimensions = ["actor", "action", "day"] as const;
export type AuditDimension = (typeof auditDimensions)[number];

export const auditSummarySchema = filterFields.extend({
  by: z.enum(auditDimensions),
}).strict().refine(ordered, rangeMessage);

export interface AuditEvent {
  sequence: number;
  jobId: string;
  action: string;
  actor: string;
  detail: unknown;
  createdAt: number;
}

export interface AuditGroup {
  key: string;
  count: number;
  jobs: number;
  first: number;
  last: number;
}

export function auditEvent(event: JobEvent): AuditEvent {
  return { ...event, detail: JSON.parse(event.detail) as unknown };
}

/** One JSON document per line, each line terminated, so exports concatenate cleanly. */
export function toNdjson(events: readonly AuditEvent[]): string {
  return events.map(event => `${JSON.stringify(event)}\n`).join("");
}

interface StageSpan {
  stage: string;
  enteredAt: number;
  leftAt: number | null;
  durationMs: number;
  sequence: number | null;
  actor: string | null;
  reason: string | null;
}

const transitionDetail = z.object({ from: z.string(), to: z.string(), reason: z.string() }).passthrough();

/**
 * Rebuild the stages a job passed through from its transition events. The first span
 * starts when the job was created; the open span runs until the job was archived, or
 * until `now` for a live job. A transition whose
 * source differs from the stage before it marks the history as inconsistent, which is
 * what a hand-edited or partially purged event log looks like.
 */
export function stageHistory(job: Job, transitions: readonly JobEvent[], now: number) {
  const moves = transitions.map(event => ({ event, detail: transitionDetail.parse(JSON.parse(event.detail)) }));
  const spans: StageSpan[] = [{
    stage: moves[0]?.detail.from ?? job.stage,
    enteredAt: job.createdAt,
    leftAt: null,
    durationMs: 0,
    sequence: null,
    actor: null,
    reason: null,
  }];
  let consistent = true;
  for (const { event, detail } of moves) {
    const previous = spans.at(-1)!;
    if (previous.stage !== detail.from) consistent = false;
    previous.leftAt = event.createdAt;
    previous.durationMs = event.createdAt - previous.enteredAt;
    spans.push({
      stage: detail.to,
      enteredAt: event.createdAt,
      leftAt: null,
      durationMs: 0,
      sequence: event.sequence,
      actor: event.actor,
      reason: detail.reason,
    });
  }
  const open = spans.at(-1)!;
  open.durationMs = Math.max(0, (job.archivedAt ?? now) - open.enteredAt);
  if (open.stage !== job.stage) consistent = false;
  const totals = Object.fromEntries(stages.map(stage => [stage, 0]));
  for (const span of spans) {
    const known = stageSchema.safeParse(span.stage);
    if (known.success) totals[known.data] = (totals[known.data] ?? 0) + span.durationMs;
  }
  return { jobId: job.id, stage: job.stage, consistent, transitions: moves.length, spans, totals };
}

export type StageHistory = ReturnType<typeof stageHistory>;

/** How many times jobs entered each stage and how long they stayed, across a project. */
export function stageDwell(histories: readonly StageHistory[]) {
  return {
    jobs: histories.length,
    inconsistent: histories.filter(history => !history.consistent).map(history => history.jobId),
    stages: stages.map(stage => {
      const spans = histories.flatMap(history => history.spans.filter(span => span.stage === stage));
      const totalMs = spans.reduce((sum, span) => sum + span.durationMs, 0);
      return {
        stage,
        label: stageLabel(stage),
        entries: spans.length,
        current: histories.filter(history => history.stage === stage).length,
        totalMs,
        averageMs: spans.length === 0 ? 0 : Math.round(totalMs / spans.length),
      };
    }),
  };
}

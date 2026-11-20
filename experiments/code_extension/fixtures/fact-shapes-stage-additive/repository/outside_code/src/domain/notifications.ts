import { z } from "zod";
import type { Stage } from "../../stage/types.ts";
import type { Job, JobEvent } from "./models.ts";
import { keySchema, stageSchema } from "./validation.ts";

export interface Subscription {
  id: string;
  project: string;
  principal: string;
  pattern: string;
  jobId: string | null;
  stage: Stage | null;
  createdAt: number;
}

export type SubscriptionFilters = Pick<Subscription, "pattern" | "jobId" | "stage">;

export interface Notification {
  id: number;
  subscriptionId: string | null;
  jobId: string;
  action: string;
  payload: unknown;
  createdAt: number;
  readAt: number | null;
}

export const subscriptionSchema = z.object({
  id: keySchema,
  // An exact action such as `job.transitioned`, or a prefix ending in a dot such as `evidence.`.
  pattern: z.string().max(80).regex(
    /^[a-z][a-z_]*(?:\.[a-z][a-z_]*)*\.?$/,
    "pattern must be an action name or a prefix ending in a dot",
  ),
  jobId: keySchema.optional(),
  stage: stageSchema.optional(),
}).strict();

export const inboxSchema = z.object({
  unread: z.enum(["true", "false"]).transform(value => value === "true").default(true),
  limit: z.coerce.number().int().min(1).max(100).default(25),
}).strict();

export const markReadSchema = z.object({
  ids: z.array(z.number().int().positive()).min(1).max(100),
}).strict();

/** Every filter a subscription sets must hold; the stage is the job's stage at collection. */
export function matchesSubscription(filters: SubscriptionFilters, event: JobEvent, stage: Stage): boolean {
  const pattern = filters.pattern;
  return (pattern.endsWith(".") ? event.action.startsWith(pattern) : event.action === pattern)
    && (filters.jobId === null || filters.jobId === event.jobId)
    && (filters.stage === null || filters.stage === stage);
}

export function sameFilters(left: SubscriptionFilters, right: SubscriptionFilters): boolean {
  return left.pattern === right.pattern && left.jobId === right.jobId && left.stage === right.stage;
}

/** The JSON body every recipient of one event receives, notification and webhook alike. */
export function eventPayload(event: JobEvent, job: Pick<Job, "project" | "title" | "stage">): string {
  return JSON.stringify({
    sequence: event.sequence,
    action: event.action,
    project: job.project,
    jobId: event.jobId,
    jobTitle: job.title,
    stage: job.stage,
    actor: event.actor,
    occurredAt: event.createdAt,
    detail: JSON.parse(event.detail) as unknown,
  });
}

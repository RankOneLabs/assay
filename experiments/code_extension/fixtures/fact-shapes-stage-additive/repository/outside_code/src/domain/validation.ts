import { z } from "zod";
import { isValue as isStage } from "../../stage/types.ts";
import { isValue as isEvidenceKind } from "../../evidence_kind/types.ts";
import { isValue as isPermission } from "../../route_permission/types.ts";
import type { Stage } from "../../stage/types.ts";
import type { EvidenceKind } from "../../evidence_kind/types.ts";
import type { RoutePermission } from "../../route_permission/types.ts";

export const keySchema = z.string().regex(/^[a-zA-Z0-9_-]{1,80}$/);
const title = z.string().trim().min(1).max(240);
const description = z.string().max(20000);
const priority = z.number().int().min(0).max(100);
const revision = z.number().int().positive();
export const stageSchema = z.custom<Stage>(v => typeof v === "string" && isStage(v));
export const kindSchema = z.custom<EvidenceKind>(v => typeof v === "string" && isEvidenceKind(v));
export const permissionSchema = z.custom<RoutePermission>(v => typeof v === "string" && isPermission(v));

export const createJobSchema = z.object({
  id: keySchema,
  title,
  description: description.default(""),
  priority: priority.default(0),
  owner: keySchema,
  project: keySchema,
  runId: keySchema.optional(),
}).strict();

export const runSchema = z.object({
  id: keySchema,
  title,
}).strict();

export const runJobsSchema = z.object({
  jobs: z.array(keySchema).min(1).max(100).refine(ids => new Set(ids).size === ids.length, "duplicate jobs"),
}).strict();

export const runListSchema = z.object({
  status: z.enum(["running", "finished"]).optional(),
  limit: z.coerce.number().int().min(1).max(100).default(50),
  offset: z.coerce.number().int().min(0).default(0),
}).strict();

export const patchJobSchema = z.object({
  title: title.optional(),
  description: description.optional(),
  priority: priority.optional(),
  owner: keySchema.optional(),
  expectedRevision: revision,
}).strict().refine(
  value => [value.title, value.description, value.priority, value.owner].some(v => v !== undefined),
  "patch requires a changed field",
);

export const transitionSchema = z.object({
  stage: stageSchema,
  expectedRevision: revision,
  reason: z.string().trim().min(1).max(2000),
}).strict();

export const evidenceSchema = z.object({
  id: keySchema,
  kind: kindSchema,
  title,
  content: z.string().min(1).max(100000),
  author: keySchema,
}).strict();

export const patchEvidenceSchema = z.object({
  title: title.optional(),
  content: z.string().min(1).max(100000).optional(),
  expectedRevision: revision,
}).strict().refine(
  value => value.title !== undefined || value.content !== undefined,
  "patch requires a changed field",
);

export const filterSchema = z.object({
  stage: stageSchema.optional(),
  owner: keySchema.optional(),
  project: keySchema.optional(),
  query: z.string().trim().max(240).optional(),
  archived: z.enum(["true", "false"]).transform(v => v === "true").optional(),
  minPriority: z.coerce.number().int().min(0).max(100).optional(),
  limit: z.coerce.number().int().min(1).max(100).default(25),
  offset: z.coerce.number().int().min(0).default(0),
}).strict();

export const grantSchema = z.object({
  principal: keySchema,
  permission: permissionSchema,
  project: keySchema,
}).strict();

export const revisionSchema = z.object({ expectedRevision: revision }).strict();

export const buildSchema = z.object({
  id: keySchema,
  sessionId: keySchema,
  worker: keySchema,
  expectedRevision: revision,
}).strict();

export const finishSchema = z.object({
  sessionId: keySchema,
  exitCode: z.number().int().min(0).max(255),
  output: z.string().max(100000),
}).strict();

export const retentionSchema = z.object({
  stage: stageSchema,
  days: z.number().int().min(1).max(3650),
}).strict();

export const bulkSchema = z.object({
  ids: z.array(keySchema).min(1).max(100).refine(ids => new Set(ids).size === ids.length),
  reason: z.string().trim().min(1).max(2000),
}).strict();

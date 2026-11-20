import { z } from "zod";
import * as stageTypes from "../../stage/types.ts";
import { keySchema, stageSchema } from "./validation.ts";

/** Escalation rules apply only to stages that are still open work. */
const escalates = (stage: stageTypes.Stage): boolean => stageTypes.stageTraits[stage].open;
const ruleStage = stageSchema.refine(escalates, "escalation rules need an open stage");

const maxAgeMinutes = z.number().int().min(1).max(525_600);
const minPriority = z.number().int().min(0).max(100);
const revision = z.number().int().positive();
const flag = z.enum(["true", "false"]).transform(value => value === "true");
const instantSchema = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
export const escalationIdSchema = z.coerce.number().int().positive().max(Number.MAX_SAFE_INTEGER);

export const ruleSchema = z.object({
  id: keySchema,
  stage: ruleStage,
  maxAgeMinutes,
  minPriority: minPriority.default(0),
  target: keySchema,
  enabled: z.boolean().default(true),
}).strict();

export const rulePatchSchema = z.object({
  stage: ruleStage.optional(),
  maxAgeMinutes: maxAgeMinutes.optional(),
  minPriority: minPriority.optional(),
  target: keySchema.optional(),
  enabled: z.boolean().optional(),
  expectedRevision: revision,
}).strict().refine(
  value => [value.stage, value.maxAgeMinutes, value.minPriority, value.target, value.enabled]
    .some(field => field !== undefined),
  "patch requires a changed field",
);

export const ruleFilterSchema = z.object({
  stage: stageSchema.optional(),
  enabled: flag.optional(),
}).strict();

export const evaluationSchema = z.object({ at: instantSchema.optional() }).strict();

export const escalationFilterSchema = z.object({
  stage: stageSchema.optional(),
  ruleId: keySchema.optional(),
  target: keySchema.optional(),
  limit: z.coerce.number().int().min(1).max(100).default(25),
  offset: z.coerce.number().int().min(0).default(0),
}).strict();

export const resolutionSchema = z.object({
  note: z.string().trim().min(1).max(2000),
}).strict();

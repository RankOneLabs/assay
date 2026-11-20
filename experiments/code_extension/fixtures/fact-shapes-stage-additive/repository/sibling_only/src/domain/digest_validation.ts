import { z } from "zod";
import { keySchema } from "./validation.ts";
import { cadences } from "./schedules.ts";

const cadence = z.enum(cadences);
const weekday = z.number().int().min(0).max(6);
const hour = z.number().int().min(0).max(23);
const utcOffsetMinutes = z.number().int().min(-720).max(840);
const instant = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
const page = {
  limit: z.coerce.number().int().min(1).max(100).default(25),
  offset: z.coerce.number().int().min(0).default(0),
};
export const digestIdSchema = z.coerce.number().int().positive().max(Number.MAX_SAFE_INTEGER);

const recurrence = z.object({
  cadence,
  weekday: weekday.nullable().default(null),
  hour,
  utcOffsetMinutes: utcOffsetMinutes.default(0),
  enabled: z.boolean().default(true),
});
/** A weekday belongs to weekly recurrences only. */
const weekdayFits = (value: { cadence: string; weekday: number | null }) =>
  (value.cadence === "weekly") === (value.weekday !== null);
const weekdayRule = "weekly schedules need a weekday and daily schedules must not have one";
export const recurrenceSchema = recurrence.strict().refine(weekdayFits, weekdayRule);
export const scheduleSchema = recurrence.extend({ id: keySchema }).strict().refine(weekdayFits, weekdayRule);

export const schedulePatchSchema = z.object({
  cadence: cadence.optional(),
  weekday: weekday.nullable().optional(),
  hour: hour.optional(),
  utcOffsetMinutes: utcOffsetMinutes.optional(),
  enabled: z.boolean().optional(),
  expectedRevision: z.number().int().positive(),
}).strict().refine(
  value => [value.cadence, value.weekday, value.hour, value.utcOffsetMinutes, value.enabled]
    .some(field => field !== undefined),
  "patch requires a changed field",
);

export const generateSchema = z.object({ at: instant.optional() }).strict();

export const dueSchema = z.object({
  at: z.coerce.number().int().min(0).max(Number.MAX_SAFE_INTEGER).optional(),
  limit: page.limit,
}).strict();

export const digestPageSchema = z.object(page).strict();

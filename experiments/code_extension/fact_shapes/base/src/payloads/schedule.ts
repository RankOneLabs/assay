import { z } from "zod";

/**
 * Validated schedule payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const scheduleSchema = z.object({
  /** Human or machine supplied title; one through 240 characters. */
  title: z.string()
    .trim()
    .min(1, "title must not be empty")
    .max(240, "title exceeds the storage limit")
    .optional(),
  /** Human or machine supplied description; one through 240 characters. */
  description: z.string()
    .trim()
    .min(1, "description must not be empty")
    .max(240, "description exceeds the storage limit")
    .optional(),
  /** Human or machine supplied projectKey; one through 240 characters. */
  projectKey: z.string()
    .trim()
    .min(1, "projectKey must not be empty")
    .max(240, "projectKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied queueKey; one through 240 characters. */
  queueKey: z.string()
    .trim()
    .min(1, "queueKey must not be empty")
    .max(240, "queueKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied expression; one through 240 characters. */
  expression: z.string()
    .trim()
    .min(1, "expression must not be empty")
    .max(240, "expression exceeds the storage limit")
    .optional(),
  /** Human or machine supplied timezone; one through 240 characters. */
  timezone: z.string()
    .trim()
    .min(1, "timezone must not be empty")
    .max(240, "timezone exceeds the storage limit")
    .optional(),
  /** Human or machine supplied inputKey; one through 240 characters. */
  inputKey: z.string()
    .trim()
    .min(1, "inputKey must not be empty")
    .max(240, "inputKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied ownerKey; one through 240 characters. */
  ownerKey: z.string()
    .trim()
    .min(1, "ownerKey must not be empty")
    .max(240, "ownerKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied region; one through 240 characters. */
  region: z.string()
    .trim()
    .min(1, "region must not be empty")
    .max(240, "region exceeds the storage limit")
    .optional(),
  /** Human or machine supplied deduplicationKey; one through 240 characters. */
  deduplicationKey: z.string()
    .trim()
    .min(1, "deduplicationKey must not be empty")
    .max(240, "deduplicationKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied calendarKey; one through 240 characters. */
  calendarKey: z.string()
    .trim()
    .min(1, "calendarKey must not be empty")
    .max(240, "calendarKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied contact; one through 240 characters. */
  contact: z.string()
    .trim()
    .min(1, "contact must not be empty")
    .max(240, "contact exceeds the storage limit")
    .optional(),
}).strict();

export type SchedulePayload = z.infer<typeof scheduleSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseSchedule(input: unknown): SchedulePayload {
  return scheduleSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchSchedule(current: SchedulePayload, patch: unknown): SchedulePayload {
  const changes = parseSchedule(patch);
  return parseSchedule({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeSchedule(input: unknown): string {
  const parsed = parseSchedule(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalSchedule(left: unknown, right: unknown): boolean {
  return serializeSchedule(left) === serializeSchedule(right);
}

import { z } from "zod";

/**
 * Validated attempt payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const attemptSchema = z.object({
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
  /** Human or machine supplied jobKey; one through 240 characters. */
  jobKey: z.string()
    .trim()
    .min(1, "jobKey must not be empty")
    .max(240, "jobKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied workerKey; one through 240 characters. */
  workerKey: z.string()
    .trim()
    .min(1, "workerKey must not be empty")
    .max(240, "workerKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied inputKey; one through 240 characters. */
  inputKey: z.string()
    .trim()
    .min(1, "inputKey must not be empty")
    .max(240, "inputKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied outputKey; one through 240 characters. */
  outputKey: z.string()
    .trim()
    .min(1, "outputKey must not be empty")
    .max(240, "outputKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied traceKey; one through 240 characters. */
  traceKey: z.string()
    .trim()
    .min(1, "traceKey must not be empty")
    .max(240, "traceKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied errorCode; one through 240 characters. */
  errorCode: z.string()
    .trim()
    .min(1, "errorCode must not be empty")
    .max(240, "errorCode exceeds the storage limit")
    .optional(),
  /** Human or machine supplied errorMessage; one through 240 characters. */
  errorMessage: z.string()
    .trim()
    .min(1, "errorMessage must not be empty")
    .max(240, "errorMessage exceeds the storage limit")
    .optional(),
  /** Human or machine supplied runtime; one through 240 characters. */
  runtime: z.string()
    .trim()
    .min(1, "runtime must not be empty")
    .max(240, "runtime exceeds the storage limit")
    .optional(),
  /** Human or machine supplied revision; one through 240 characters. */
  revision: z.string()
    .trim()
    .min(1, "revision must not be empty")
    .max(240, "revision exceeds the storage limit")
    .optional(),
  /** Human or machine supplied checkpointKey; one through 240 characters. */
  checkpointKey: z.string()
    .trim()
    .min(1, "checkpointKey must not be empty")
    .max(240, "checkpointKey exceeds the storage limit")
    .optional(),
}).strict();

export type AttemptPayload = z.infer<typeof attemptSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseAttempt(input: unknown): AttemptPayload {
  return attemptSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchAttempt(current: AttemptPayload, patch: unknown): AttemptPayload {
  const changes = parseAttempt(patch);
  return parseAttempt({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeAttempt(input: unknown): string {
  const parsed = parseAttempt(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalAttempt(left: unknown, right: unknown): boolean {
  return serializeAttempt(left) === serializeAttempt(right);
}

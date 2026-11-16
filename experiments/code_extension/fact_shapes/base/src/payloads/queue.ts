import { z } from "zod";

/**
 * Validated queue payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const queueSchema = z.object({
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
  /** Human or machine supplied partitionKey; one through 240 characters. */
  partitionKey: z.string()
    .trim()
    .min(1, "partitionKey must not be empty")
    .max(240, "partitionKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied dispatchRule; one through 240 characters. */
  dispatchRule: z.string()
    .trim()
    .min(1, "dispatchRule must not be empty")
    .max(240, "dispatchRule exceeds the storage limit")
    .optional(),
  /** Human or machine supplied retryRule; one through 240 characters. */
  retryRule: z.string()
    .trim()
    .min(1, "retryRule must not be empty")
    .max(240, "retryRule exceeds the storage limit")
    .optional(),
  /** Human or machine supplied priorityRule; one through 240 characters. */
  priorityRule: z.string()
    .trim()
    .min(1, "priorityRule must not be empty")
    .max(240, "priorityRule exceeds the storage limit")
    .optional(),
  /** Human or machine supplied retention; one through 240 characters. */
  retention: z.string()
    .trim()
    .min(1, "retention must not be empty")
    .max(240, "retention exceeds the storage limit")
    .optional(),
  /** Human or machine supplied contact; one through 240 characters. */
  contact: z.string()
    .trim()
    .min(1, "contact must not be empty")
    .max(240, "contact exceeds the storage limit")
    .optional(),
  /** Human or machine supplied label; one through 240 characters. */
  label: z.string()
    .trim()
    .min(1, "label must not be empty")
    .max(240, "label exceeds the storage limit")
    .optional(),
}).strict();

export type QueuePayload = z.infer<typeof queueSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseQueue(input: unknown): QueuePayload {
  return queueSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchQueue(current: QueuePayload, patch: unknown): QueuePayload {
  const changes = parseQueue(patch);
  return parseQueue({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeQueue(input: unknown): string {
  const parsed = parseQueue(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalQueue(left: unknown, right: unknown): boolean {
  return serializeQueue(left) === serializeQueue(right);
}

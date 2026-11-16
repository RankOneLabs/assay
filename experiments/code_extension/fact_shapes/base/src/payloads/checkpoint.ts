import { z } from "zod";

/**
 * Validated checkpoint payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const checkpointSchema = z.object({
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
  /** Human or machine supplied attemptKey; one through 240 characters. */
  attemptKey: z.string()
    .trim()
    .min(1, "attemptKey must not be empty")
    .max(240, "attemptKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied storageKey; one through 240 characters. */
  storageKey: z.string()
    .trim()
    .min(1, "storageKey must not be empty")
    .max(240, "storageKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied checksum; one through 240 characters. */
  checksum: z.string()
    .trim()
    .min(1, "checksum must not be empty")
    .max(240, "checksum exceeds the storage limit")
    .optional(),
  /** Human or machine supplied format; one through 240 characters. */
  format: z.string()
    .trim()
    .min(1, "format must not be empty")
    .max(240, "format exceeds the storage limit")
    .optional(),
  /** Human or machine supplied version; one through 240 characters. */
  version: z.string()
    .trim()
    .min(1, "version must not be empty")
    .max(240, "version exceeds the storage limit")
    .optional(),
  /** Human or machine supplied producer; one through 240 characters. */
  producer: z.string()
    .trim()
    .min(1, "producer must not be empty")
    .max(240, "producer exceeds the storage limit")
    .optional(),
  /** Human or machine supplied resumeToken; one through 240 characters. */
  resumeToken: z.string()
    .trim()
    .min(1, "resumeToken must not be empty")
    .max(240, "resumeToken exceeds the storage limit")
    .optional(),
  /** Human or machine supplied region; one through 240 characters. */
  region: z.string()
    .trim()
    .min(1, "region must not be empty")
    .max(240, "region exceeds the storage limit")
    .optional(),
  /** Human or machine supplied encryptionKey; one through 240 characters. */
  encryptionKey: z.string()
    .trim()
    .min(1, "encryptionKey must not be empty")
    .max(240, "encryptionKey exceeds the storage limit")
    .optional(),
}).strict();

export type CheckpointPayload = z.infer<typeof checkpointSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseCheckpoint(input: unknown): CheckpointPayload {
  return checkpointSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchCheckpoint(current: CheckpointPayload, patch: unknown): CheckpointPayload {
  const changes = parseCheckpoint(patch);
  return parseCheckpoint({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeCheckpoint(input: unknown): string {
  const parsed = parseCheckpoint(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalCheckpoint(left: unknown, right: unknown): boolean {
  return serializeCheckpoint(left) === serializeCheckpoint(right);
}

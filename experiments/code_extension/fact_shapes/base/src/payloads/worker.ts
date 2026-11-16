import { z } from "zod";

/**
 * Validated worker payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const workerSchema = z.object({
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
  /** Human or machine supplied poolKey; one through 240 characters. */
  poolKey: z.string()
    .trim()
    .min(1, "poolKey must not be empty")
    .max(240, "poolKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied hostKey; one through 240 characters. */
  hostKey: z.string()
    .trim()
    .min(1, "hostKey must not be empty")
    .max(240, "hostKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied runtime; one through 240 characters. */
  runtime: z.string()
    .trim()
    .min(1, "runtime must not be empty")
    .max(240, "runtime exceeds the storage limit")
    .optional(),
  /** Human or machine supplied version; one through 240 characters. */
  version: z.string()
    .trim()
    .min(1, "version must not be empty")
    .max(240, "version exceeds the storage limit")
    .optional(),
  /** Human or machine supplied region; one through 240 characters. */
  region: z.string()
    .trim()
    .min(1, "region must not be empty")
    .max(240, "region exceeds the storage limit")
    .optional(),
  /** Human or machine supplied architecture; one through 240 characters. */
  architecture: z.string()
    .trim()
    .min(1, "architecture must not be empty")
    .max(240, "architecture exceeds the storage limit")
    .optional(),
  /** Human or machine supplied capability; one through 240 characters. */
  capability: z.string()
    .trim()
    .min(1, "capability must not be empty")
    .max(240, "capability exceeds the storage limit")
    .optional(),
  /** Human or machine supplied contact; one through 240 characters. */
  contact: z.string()
    .trim()
    .min(1, "contact must not be empty")
    .max(240, "contact exceeds the storage limit")
    .optional(),
  /** Human or machine supplied certificate; one through 240 characters. */
  certificate: z.string()
    .trim()
    .min(1, "certificate must not be empty")
    .max(240, "certificate exceeds the storage limit")
    .optional(),
  /** Human or machine supplied imageKey; one through 240 characters. */
  imageKey: z.string()
    .trim()
    .min(1, "imageKey must not be empty")
    .max(240, "imageKey exceeds the storage limit")
    .optional(),
}).strict();

export type WorkerPayload = z.infer<typeof workerSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseWorker(input: unknown): WorkerPayload {
  return workerSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchWorker(current: WorkerPayload, patch: unknown): WorkerPayload {
  const changes = parseWorker(patch);
  return parseWorker({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeWorker(input: unknown): string {
  const parsed = parseWorker(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalWorker(left: unknown, right: unknown): boolean {
  return serializeWorker(left) === serializeWorker(right);
}

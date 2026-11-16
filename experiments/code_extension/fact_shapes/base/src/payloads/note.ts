import { z } from "zod";

/**
 * Validated note payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const noteSchema = z.object({
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
  /** Human or machine supplied caseKey; one through 240 characters. */
  caseKey: z.string()
    .trim()
    .min(1, "caseKey must not be empty")
    .max(240, "caseKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied authorKey; one through 240 characters. */
  authorKey: z.string()
    .trim()
    .min(1, "authorKey must not be empty")
    .max(240, "authorKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied body; one through 240 characters. */
  body: z.string()
    .trim()
    .min(1, "body must not be empty")
    .max(240, "body exceeds the storage limit")
    .optional(),
  /** Human or machine supplied locale; one through 240 characters. */
  locale: z.string()
    .trim()
    .min(1, "locale must not be empty")
    .max(240, "locale exceeds the storage limit")
    .optional(),
  /** Human or machine supplied category; one through 240 characters. */
  category: z.string()
    .trim()
    .min(1, "category must not be empty")
    .max(240, "category exceeds the storage limit")
    .optional(),
  /** Human or machine supplied sourceKey; one through 240 characters. */
  sourceKey: z.string()
    .trim()
    .min(1, "sourceKey must not be empty")
    .max(240, "sourceKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied threadKey; one through 240 characters. */
  threadKey: z.string()
    .trim()
    .min(1, "threadKey must not be empty")
    .max(240, "threadKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied parentKey; one through 240 characters. */
  parentKey: z.string()
    .trim()
    .min(1, "parentKey must not be empty")
    .max(240, "parentKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied correlationKey; one through 240 characters. */
  correlationKey: z.string()
    .trim()
    .min(1, "correlationKey must not be empty")
    .max(240, "correlationKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied visibility; one through 240 characters. */
  visibility: z.string()
    .trim()
    .min(1, "visibility must not be empty")
    .max(240, "visibility exceeds the storage limit")
    .optional(),
}).strict();

export type NotePayload = z.infer<typeof noteSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseNote(input: unknown): NotePayload {
  return noteSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchNote(current: NotePayload, patch: unknown): NotePayload {
  const changes = parseNote(patch);
  return parseNote({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeNote(input: unknown): string {
  const parsed = parseNote(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalNote(left: unknown, right: unknown): boolean {
  return serializeNote(left) === serializeNote(right);
}

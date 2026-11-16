import { z } from "zod";

/**
 * Validated case payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const caseSchema = z.object({
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
  /** Human or machine supplied ownerKey; one through 240 characters. */
  ownerKey: z.string()
    .trim()
    .min(1, "ownerKey must not be empty")
    .max(240, "ownerKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied projectKey; one through 240 characters. */
  projectKey: z.string()
    .trim()
    .min(1, "projectKey must not be empty")
    .max(240, "projectKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied externalKey; one through 240 characters. */
  externalKey: z.string()
    .trim()
    .min(1, "externalKey must not be empty")
    .max(240, "externalKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied category; one through 240 characters. */
  category: z.string()
    .trim()
    .min(1, "category must not be empty")
    .max(240, "category exceeds the storage limit")
    .optional(),
  /** Human or machine supplied subject; one through 240 characters. */
  subject: z.string()
    .trim()
    .min(1, "subject must not be empty")
    .max(240, "subject exceeds the storage limit")
    .optional(),
  /** Human or machine supplied reporter; one through 240 characters. */
  reporter: z.string()
    .trim()
    .min(1, "reporter must not be empty")
    .max(240, "reporter exceeds the storage limit")
    .optional(),
  /** Human or machine supplied region; one through 240 characters. */
  region: z.string()
    .trim()
    .min(1, "region must not be empty")
    .max(240, "region exceeds the storage limit")
    .optional(),
  /** Human or machine supplied locale; one through 240 characters. */
  locale: z.string()
    .trim()
    .min(1, "locale must not be empty")
    .max(240, "locale exceeds the storage limit")
    .optional(),
  /** Human or machine supplied summary; one through 240 characters. */
  summary: z.string()
    .trim()
    .min(1, "summary must not be empty")
    .max(240, "summary exceeds the storage limit")
    .optional(),
  /** Human or machine supplied resolution; one through 240 characters. */
  resolution: z.string()
    .trim()
    .min(1, "resolution must not be empty")
    .max(240, "resolution exceeds the storage limit")
    .optional(),
}).strict();

export type CasePayload = z.infer<typeof caseSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseCase(input: unknown): CasePayload {
  return caseSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchCase(current: CasePayload, patch: unknown): CasePayload {
  const changes = parseCase(patch);
  return parseCase({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeCase(input: unknown): string {
  const parsed = parseCase(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalCase(left: unknown, right: unknown): boolean {
  return serializeCase(left) === serializeCase(right);
}

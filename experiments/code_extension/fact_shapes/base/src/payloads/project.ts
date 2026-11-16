import { z } from "zod";

/**
 * Validated project payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const projectSchema = z.object({
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
  /** Human or machine supplied workspaceKey; one through 240 characters. */
  workspaceKey: z.string()
    .trim()
    .min(1, "workspaceKey must not be empty")
    .max(240, "workspaceKey exceeds the storage limit")
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
  /** Human or machine supplied locale; one through 240 characters. */
  locale: z.string()
    .trim()
    .min(1, "locale must not be empty")
    .max(240, "locale exceeds the storage limit")
    .optional(),
  /** Human or machine supplied repositoryKey; one through 240 characters. */
  repositoryKey: z.string()
    .trim()
    .min(1, "repositoryKey must not be empty")
    .max(240, "repositoryKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied contact; one through 240 characters. */
  contact: z.string()
    .trim()
    .min(1, "contact must not be empty")
    .max(240, "contact exceeds the storage limit")
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
  /** Human or machine supplied costCenter; one through 240 characters. */
  costCenter: z.string()
    .trim()
    .min(1, "costCenter must not be empty")
    .max(240, "costCenter exceeds the storage limit")
    .optional(),
  /** Human or machine supplied retention; one through 240 characters. */
  retention: z.string()
    .trim()
    .min(1, "retention must not be empty")
    .max(240, "retention exceeds the storage limit")
    .optional(),
}).strict();

export type ProjectPayload = z.infer<typeof projectSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseProject(input: unknown): ProjectPayload {
  return projectSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchProject(current: ProjectPayload, patch: unknown): ProjectPayload {
  const changes = parseProject(patch);
  return parseProject({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeProject(input: unknown): string {
  const parsed = parseProject(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalProject(left: unknown, right: unknown): boolean {
  return serializeProject(left) === serializeProject(right);
}

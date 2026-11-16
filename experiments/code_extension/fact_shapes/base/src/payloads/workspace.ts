import { z } from "zod";

/**
 * Validated workspace payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const workspaceSchema = z.object({
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
  /** Human or machine supplied organizationKey; one through 240 characters. */
  organizationKey: z.string()
    .trim()
    .min(1, "organizationKey must not be empty")
    .max(240, "organizationKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied contact; one through 240 characters. */
  contact: z.string()
    .trim()
    .min(1, "contact must not be empty")
    .max(240, "contact exceeds the storage limit")
    .optional(),
  /** Human or machine supplied domain; one through 240 characters. */
  domain: z.string()
    .trim()
    .min(1, "domain must not be empty")
    .max(240, "domain exceeds the storage limit")
    .optional(),
  /** Human or machine supplied externalKey; one through 240 characters. */
  externalKey: z.string()
    .trim()
    .min(1, "externalKey must not be empty")
    .max(240, "externalKey exceeds the storage limit")
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
  /** Human or machine supplied timezone; one through 240 characters. */
  timezone: z.string()
    .trim()
    .min(1, "timezone must not be empty")
    .max(240, "timezone exceeds the storage limit")
    .optional(),
}).strict();

export type WorkspacePayload = z.infer<typeof workspaceSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseWorkspace(input: unknown): WorkspacePayload {
  return workspaceSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchWorkspace(current: WorkspacePayload, patch: unknown): WorkspacePayload {
  const changes = parseWorkspace(patch);
  return parseWorkspace({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeWorkspace(input: unknown): string {
  const parsed = parseWorkspace(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalWorkspace(left: unknown, right: unknown): boolean {
  return serializeWorkspace(left) === serializeWorkspace(right);
}

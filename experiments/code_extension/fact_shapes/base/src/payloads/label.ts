import { z } from "zod";

/**
 * Validated label payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const labelSchema = z.object({
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
  /** Human or machine supplied color; one through 240 characters. */
  color: z.string()
    .trim()
    .min(1, "color must not be empty")
    .max(240, "color exceeds the storage limit")
    .optional(),
  /** Human or machine supplied category; one through 240 characters. */
  category: z.string()
    .trim()
    .min(1, "category must not be empty")
    .max(240, "category exceeds the storage limit")
    .optional(),
  /** Human or machine supplied namespace; one through 240 characters. */
  namespace: z.string()
    .trim()
    .min(1, "namespace must not be empty")
    .max(240, "namespace exceeds the storage limit")
    .optional(),
  /** Human or machine supplied externalKey; one through 240 characters. */
  externalKey: z.string()
    .trim()
    .min(1, "externalKey must not be empty")
    .max(240, "externalKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied locale; one through 240 characters. */
  locale: z.string()
    .trim()
    .min(1, "locale must not be empty")
    .max(240, "locale exceeds the storage limit")
    .optional(),
  /** Human or machine supplied displayName; one through 240 characters. */
  displayName: z.string()
    .trim()
    .min(1, "displayName must not be empty")
    .max(240, "displayName exceeds the storage limit")
    .optional(),
  /** Human or machine supplied shortName; one through 240 characters. */
  shortName: z.string()
    .trim()
    .min(1, "shortName must not be empty")
    .max(240, "shortName exceeds the storage limit")
    .optional(),
  /** Human or machine supplied helpText; one through 240 characters. */
  helpText: z.string()
    .trim()
    .min(1, "helpText must not be empty")
    .max(240, "helpText exceeds the storage limit")
    .optional(),
}).strict();

export type LabelPayload = z.infer<typeof labelSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseLabel(input: unknown): LabelPayload {
  return labelSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchLabel(current: LabelPayload, patch: unknown): LabelPayload {
  const changes = parseLabel(patch);
  return parseLabel({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeLabel(input: unknown): string {
  const parsed = parseLabel(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalLabel(left: unknown, right: unknown): boolean {
  return serializeLabel(left) === serializeLabel(right);
}

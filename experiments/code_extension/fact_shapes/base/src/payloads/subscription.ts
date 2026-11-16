import { z } from "zod";

/**
 * Validated subscription payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const subscriptionSchema = z.object({
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
  /** Human or machine supplied eventFilter; one through 240 characters. */
  eventFilter: z.string()
    .trim()
    .min(1, "eventFilter must not be empty")
    .max(240, "eventFilter exceeds the storage limit")
    .optional(),
  /** Human or machine supplied endpoint; one through 240 characters. */
  endpoint: z.string()
    .trim()
    .min(1, "endpoint must not be empty")
    .max(240, "endpoint exceeds the storage limit")
    .optional(),
  /** Human or machine supplied secretKey; one through 240 characters. */
  secretKey: z.string()
    .trim()
    .min(1, "secretKey must not be empty")
    .max(240, "secretKey exceeds the storage limit")
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
  /** Human or machine supplied region; one through 240 characters. */
  region: z.string()
    .trim()
    .min(1, "region must not be empty")
    .max(240, "region exceeds the storage limit")
    .optional(),
  /** Human or machine supplied contact; one through 240 characters. */
  contact: z.string()
    .trim()
    .min(1, "contact must not be empty")
    .max(240, "contact exceeds the storage limit")
    .optional(),
  /** Human or machine supplied deduplicationKey; one through 240 characters. */
  deduplicationKey: z.string()
    .trim()
    .min(1, "deduplicationKey must not be empty")
    .max(240, "deduplicationKey exceeds the storage limit")
    .optional(),
}).strict();

export type SubscriptionPayload = z.infer<typeof subscriptionSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseSubscription(input: unknown): SubscriptionPayload {
  return subscriptionSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchSubscription(current: SubscriptionPayload, patch: unknown): SubscriptionPayload {
  const changes = parseSubscription(patch);
  return parseSubscription({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeSubscription(input: unknown): string {
  const parsed = parseSubscription(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalSubscription(left: unknown, right: unknown): boolean {
  return serializeSubscription(left) === serializeSubscription(right);
}

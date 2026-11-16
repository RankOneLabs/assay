import { z } from "zod";

/**
 * Validated delivery payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const deliverySchema = z.object({
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
  /** Human or machine supplied subscriptionKey; one through 240 characters. */
  subscriptionKey: z.string()
    .trim()
    .min(1, "subscriptionKey must not be empty")
    .max(240, "subscriptionKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied eventKey; one through 240 characters. */
  eventKey: z.string()
    .trim()
    .min(1, "eventKey must not be empty")
    .max(240, "eventKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied endpoint; one through 240 characters. */
  endpoint: z.string()
    .trim()
    .min(1, "endpoint must not be empty")
    .max(240, "endpoint exceeds the storage limit")
    .optional(),
  /** Human or machine supplied requestKey; one through 240 characters. */
  requestKey: z.string()
    .trim()
    .min(1, "requestKey must not be empty")
    .max(240, "requestKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied responseKey; one through 240 characters. */
  responseKey: z.string()
    .trim()
    .min(1, "responseKey must not be empty")
    .max(240, "responseKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied errorCode; one through 240 characters. */
  errorCode: z.string()
    .trim()
    .min(1, "errorCode must not be empty")
    .max(240, "errorCode exceeds the storage limit")
    .optional(),
  /** Human or machine supplied traceKey; one through 240 characters. */
  traceKey: z.string()
    .trim()
    .min(1, "traceKey must not be empty")
    .max(240, "traceKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied region; one through 240 characters. */
  region: z.string()
    .trim()
    .min(1, "region must not be empty")
    .max(240, "region exceeds the storage limit")
    .optional(),
  /** Human or machine supplied format; one through 240 characters. */
  format: z.string()
    .trim()
    .min(1, "format must not be empty")
    .max(240, "format exceeds the storage limit")
    .optional(),
  /** Human or machine supplied checksum; one through 240 characters. */
  checksum: z.string()
    .trim()
    .min(1, "checksum must not be empty")
    .max(240, "checksum exceeds the storage limit")
    .optional(),
}).strict();

export type DeliveryPayload = z.infer<typeof deliverySchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseDelivery(input: unknown): DeliveryPayload {
  return deliverySchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchDelivery(current: DeliveryPayload, patch: unknown): DeliveryPayload {
  const changes = parseDelivery(patch);
  return parseDelivery({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeDelivery(input: unknown): string {
  const parsed = parseDelivery(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalDelivery(left: unknown, right: unknown): boolean {
  return serializeDelivery(left) === serializeDelivery(right);
}

import { z } from "zod";

/**
 * Validated attachment payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const attachmentSchema = z.object({
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
  /** Human or machine supplied artifactKey; one through 240 characters. */
  artifactKey: z.string()
    .trim()
    .min(1, "artifactKey must not be empty")
    .max(240, "artifactKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied filename; one through 240 characters. */
  filename: z.string()
    .trim()
    .min(1, "filename must not be empty")
    .max(240, "filename exceeds the storage limit")
    .optional(),
  /** Human or machine supplied mediaType; one through 240 characters. */
  mediaType: z.string()
    .trim()
    .min(1, "mediaType must not be empty")
    .max(240, "mediaType exceeds the storage limit")
    .optional(),
  /** Human or machine supplied checksum; one through 240 characters. */
  checksum: z.string()
    .trim()
    .min(1, "checksum must not be empty")
    .max(240, "checksum exceeds the storage limit")
    .optional(),
  /** Human or machine supplied sourceKey; one through 240 characters. */
  sourceKey: z.string()
    .trim()
    .min(1, "sourceKey must not be empty")
    .max(240, "sourceKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied ownerKey; one through 240 characters. */
  ownerKey: z.string()
    .trim()
    .min(1, "ownerKey must not be empty")
    .max(240, "ownerKey exceeds the storage limit")
    .optional(),
  /** Human or machine supplied caption; one through 240 characters. */
  caption: z.string()
    .trim()
    .min(1, "caption must not be empty")
    .max(240, "caption exceeds the storage limit")
    .optional(),
  /** Human or machine supplied locale; one through 240 characters. */
  locale: z.string()
    .trim()
    .min(1, "locale must not be empty")
    .max(240, "locale exceeds the storage limit")
    .optional(),
  /** Human or machine supplied retention; one through 240 characters. */
  retention: z.string()
    .trim()
    .min(1, "retention must not be empty")
    .max(240, "retention exceeds the storage limit")
    .optional(),
}).strict();

export type AttachmentPayload = z.infer<typeof attachmentSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseAttachment(input: unknown): AttachmentPayload {
  return attachmentSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchAttachment(current: AttachmentPayload, patch: unknown): AttachmentPayload {
  const changes = parseAttachment(patch);
  return parseAttachment({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeAttachment(input: unknown): string {
  const parsed = parseAttachment(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalAttachment(left: unknown, right: unknown): boolean {
  return serializeAttachment(left) === serializeAttachment(right);
}

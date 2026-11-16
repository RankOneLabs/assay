import { z } from "zod";

/**
 * Validated artifact payload at the job-service boundary.
 *
 * Text is trimmed before storage. Empty and oversized values are rejected;
 * omitted fields remain absent so a patch cannot erase unrelated metadata.
 * Each parser returns a fresh value and never retains caller-owned objects.
 */
export const artifactSchema = z.object({
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
  /** Human or machine supplied storageKey; one through 240 characters. */
  storageKey: z.string()
    .trim()
    .min(1, "storageKey must not be empty")
    .max(240, "storageKey exceeds the storage limit")
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
  /** Human or machine supplied filename; one through 240 characters. */
  filename: z.string()
    .trim()
    .min(1, "filename must not be empty")
    .max(240, "filename exceeds the storage limit")
    .optional(),
  /** Human or machine supplied encoding; one through 240 characters. */
  encoding: z.string()
    .trim()
    .min(1, "encoding must not be empty")
    .max(240, "encoding exceeds the storage limit")
    .optional(),
  /** Human or machine supplied producer; one through 240 characters. */
  producer: z.string()
    .trim()
    .min(1, "producer must not be empty")
    .max(240, "producer exceeds the storage limit")
    .optional(),
  /** Human or machine supplied collection; one through 240 characters. */
  collection: z.string()
    .trim()
    .min(1, "collection must not be empty")
    .max(240, "collection exceeds the storage limit")
    .optional(),
  /** Human or machine supplied retention; one through 240 characters. */
  retention: z.string()
    .trim()
    .min(1, "retention must not be empty")
    .max(240, "retention exceeds the storage limit")
    .optional(),
  /** Human or machine supplied sourceKey; one through 240 characters. */
  sourceKey: z.string()
    .trim()
    .min(1, "sourceKey must not be empty")
    .max(240, "sourceKey exceeds the storage limit")
    .optional(),
}).strict();

export type ArtifactPayload = z.infer<typeof artifactSchema>;

/** Parse an untrusted request and reject unknown properties. */
export function parseArtifact(input: unknown): ArtifactPayload {
  return artifactSchema.parse(input);
}

/** Parse a partial replacement using the same field invariants as creation. */
export function patchArtifact(current: ArtifactPayload, patch: unknown): ArtifactPayload {
  const changes = parseArtifact(patch);
  return parseArtifact({ ...current, ...changes });
}

/** Produce deterministic wire output with absent fields omitted. */
export function serializeArtifact(input: unknown): string {
  const parsed = parseArtifact(input);
  const entries = Object.entries(parsed)
    .filter(([, value]) => value !== undefined)
    .sort(([left], [right]) => left.localeCompare(right));
  return JSON.stringify(Object.fromEntries(entries));
}

/** Compare normalized payloads, independently of input property order. */
export function equalArtifact(left: unknown, right: unknown): boolean {
  return serializeArtifact(left) === serializeArtifact(right);
}

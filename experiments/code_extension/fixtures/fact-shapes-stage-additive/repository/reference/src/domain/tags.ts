import { z } from "zod";

const maxTagLength = 40;
export const maxTagsPerJob = 20;
const maxMergeSources = 20;

/**
 * Tags are lowercase slugs. Input is trimmed and lowercased, and runs of spaces or
 * underscores become a single hyphen, so "Needs Review" and "needs_review" are one tag.
 */
export const tagSchema = z.string()
  .transform(value => value.trim().toLowerCase().replace(/[\s_]+/g, "-"))
  .pipe(z.string()
    .min(1, "tag is empty")
    .max(maxTagLength, `tag is longer than ${maxTagLength} characters`)
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "tag must contain letters, digits and single hyphens"));

export const addTagsSchema = z.object({
  tags: z.array(tagSchema).min(1).max(maxTagsPerJob),
}).strict();

export const renameTagSchema = z.object({
  from: tagSchema,
  to: tagSchema,
}).strict().refine(value => value.from !== value.to, "rename requires a different tag");

export const mergeTagsSchema = z.object({
  sources: z.array(tagSchema).min(1).max(maxMergeSources),
  target: tagSchema,
}).strict().refine(
  value => new Set(value.sources).size === value.sources.length,
  "merge sources must be distinct",
).refine(value => !value.sources.includes(value.target), "merge target cannot be a source");

export interface JobTag {
  tag: string;
  addedBy: string;
  createdAt: number;
}

export interface TagCount {
  tag: string;
  jobs: number;
  archived: number;
}

import { z } from "zod";
import type { Stage } from "../../stage/types.ts";
import { ServiceError } from "./errors.ts";
import { keySchema, stageSchema } from "./validation.ts";
import { tagSchema } from "./tags.ts";

export const maxQueryLength = 500;
const maxTextLength = 240;
const maxTagTerms = 10;

/**
 * A parsed job search. The text form is whitespace-separated terms: `tag:x` (repeatable,
 * all must match), `owner:y`, `stage:z`, `priority>=n` / `priority<=n` / `priority:n`,
 * `archived:true|false`, and free words, matched together as one phrase in title or description.
 */
export interface SearchQuery {
  tags: string[];
  owner?: string;
  stage?: Stage;
  minPriority?: number;
  maxPriority?: number;
  archived: boolean;
  text?: string;
}

const priorityValue = z.string()
  .regex(/^\d{1,3}$/, "priority must be a whole number")
  .transform(Number)
  .pipe(z.number().max(100, "priority must be at most 100"));
const archivedValue = z.enum(["true", "false"]).transform(value => value === "true");

function fail(message: string, position: number): never {
  throw new ServiceError(400, "invalid_query", `${message} (at position ${position})`, { position });
}

function value<T>(schema: z.ZodType<T>, raw: string, field: string, position: number): T {
  const result = schema.safeParse(raw);
  if (!result.success) fail(`invalid ${field} "${raw}": ${result.error.issues[0]?.message}`, position);
  return result.data;
}

export function parseQuery(source: string): SearchQuery {
  if (source.length > maxQueryLength) fail(`query is longer than ${maxQueryLength} characters`, maxQueryLength);
  const query: SearchQuery = { tags: [], archived: false };
  const words: string[] = [];
  const seen = new Set<string>();
  for (const match of source.matchAll(/\S+/g)) {
    const [token, at] = [match[0], match.index];
    const term = /^([a-zA-Z]+)(>=|<=|:|=)(.*)$/.exec(token);
    if (!term) {
      if (/[:<>=]/.test(token)) fail(`malformed term "${token}"`, at);
      words.push(token);
      continue;
    }
    const [, name, operator, raw] = term;
    const field = name.toLowerCase();
    if (!raw) fail(`${field} needs a value`, at);
    if (field !== "priority" && operator !== ":") fail(`${field} terms use ":"`, at);
    if (field !== "tag" && field !== "priority") {
      if (seen.has(field)) fail(`${field} may appear only once`, at);
      seen.add(field);
    }
    if (field === "tag") {
      const tag = value(tagSchema, raw, "tag", at);
      if (!query.tags.includes(tag)) query.tags.push(tag);
      if (query.tags.length > maxTagTerms) fail(`at most ${maxTagTerms} tag terms`, at);
    } else if (field === "owner") {
      query.owner = value(keySchema, raw, "owner", at);
    } else if (field === "stage") {
      query.stage = value(stageSchema, raw, "stage", at);
    } else if (field === "archived") {
      query.archived = value(archivedValue, raw, "archived", at);
    } else if (field === "priority") {
      const bound = value(priorityValue, raw, "priority", at);
      if (operator !== "<=") query.minPriority = Math.max(query.minPriority ?? 0, bound);
      if (operator !== ">=") query.maxPriority = Math.min(query.maxPriority ?? 100, bound);
      if ((query.minPriority ?? 0) > (query.maxPriority ?? 100)) fail("priority range is empty", at);
    } else {
      fail(`unknown field "${field}"`, at);
    }
  }
  if (words.length) {
    query.text = words.join(" ");
    if (query.text.length > maxTextLength) fail(`free text is longer than ${maxTextLength} characters`, 0);
  }
  return query;
}

/** Canonical text form; parsing it yields an equal query. */
export function formatQuery(query: SearchQuery): string {
  const terms = query.tags.map(tag => `tag:${tag}`);
  if (query.owner !== undefined) terms.push(`owner:${query.owner}`);
  if (query.stage !== undefined) terms.push(`stage:${query.stage}`);
  if (query.minPriority !== undefined && query.minPriority === query.maxPriority) {
    terms.push(`priority:${query.minPriority}`);
  } else {
    if (query.minPriority !== undefined) terms.push(`priority>=${query.minPriority}`);
    if (query.maxPriority !== undefined) terms.push(`priority<=${query.maxPriority}`);
  }
  if (query.archived) terms.push("archived:true");
  if (query.text !== undefined) terms.push(query.text);
  return terms.join(" ");
}

import { z } from "zod";
import type { Database } from "bun:sqlite";
import type { Job, Page, Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { keySchema, revisionSchema } from "../domain/validation.ts";
import { forbidden, limitExceeded, missing } from "../domain/errors.ts";
import { formatQuery, maxQueryLength, parseQuery } from "../domain/search_query.ts";
import { SavedSearchRepository, type SavedSearch } from "../repositories/searches.ts";
import { TagRepository } from "../repositories/tags.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { AccessService } from "./access.ts";

export const maxSavedSearches = 50;
const nameSchema = z.string().trim().min(1).max(120);
const querySchema = z.string().max(maxQueryLength);

const createSchema = z.object({
  id: keySchema,
  name: nameSchema,
  query: querySchema,
  shared: z.boolean().default(false),
}).strict();

const updateSchema = z.object({
  name: nameSchema.optional(),
  query: querySchema.optional(),
  shared: z.boolean().optional(),
  expectedRevision: z.number().int().positive(),
}).strict().refine(
  value => [value.name, value.query, value.shared].some(field => field !== undefined),
  "update requires a changed field",
);

/**
 * Saved searches belong to one principal. Sharing one with the project makes it
 * visible to every reader there and requires write permission.
 */
export class SearchService {
  constructor(
    private readonly db: Database,
    private readonly searches: SavedSearchRepository,
    private readonly tags: TagRepository,
    private readonly jobs: JobRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  create(actor: Principal, input: unknown): SavedSearch {
    this.access.require(actor, readAccess);
    const parsed = createSchema.parse(input);
    if (parsed.shared) this.access.require(actor, "case_write");
    const query = formatQuery(parseQuery(parsed.query));
    return this.db.transaction(() => {
      if (this.searches.countOwned(actor.project, actor.id) >= maxSavedSearches) {
        limitExceeded(`a principal keeps at most ${maxSavedSearches} saved searches`);
      }
      return this.searches.create({ ...parsed, query, project: actor.project, owner: actor.id }, this.now());
    })();
  }

  list(actor: Principal, limit: number, offset: number): Page<SavedSearch> {
    this.access.require(actor, readAccess);
    return this.searches.visible(actor.project, actor.id, limit, offset);
  }

  /** Searches another principal has not shared are reported as missing, not forbidden. */
  get(actor: Principal, id: string): SavedSearch {
    this.access.require(actor, readAccess);
    const search = this.searches.require(id);
    if (search.project !== actor.project || (!search.shared && search.owner !== actor.id)) {
      missing("saved search", id);
    }
    return search;
  }

  update(actor: Principal, id: string, input: unknown): SavedSearch {
    const parsed = updateSchema.parse(input);
    const query = parsed.query === undefined ? undefined : formatQuery(parseQuery(parsed.query));
    return this.db.transaction(() => {
      const current = this.get(actor, id);
      if (current.owner !== actor.id) forbidden("only the owner can change a saved search");
      const shared = parsed.shared ?? current.shared;
      if (shared && !current.shared) this.access.require(actor, "case_write");
      return this.searches.update(id, {
        name: parsed.name ?? current.name,
        query: query ?? current.query,
        shared,
      }, parsed.expectedRevision, this.now());
    })();
  }

  /** Owners delete their own searches; administrators may also remove shared ones. */
  remove(actor: Principal, id: string, input: unknown): SavedSearch {
    const parsed = revisionSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.get(actor, id);
      if (current.owner !== actor.id) this.access.require(actor, "case_admin");
      return this.searches.delete(id, parsed.expectedRevision);
    })();
  }

  /** Runs with the caller's own read access; a shared search never widens it. */
  run(actor: Principal, id: string, limit: number, offset: number): Page<Job> {
    const search = this.get(actor, id);
    const ids = this.tags.search(actor.project, parseQuery(search.query), limit, offset);
    return { ...ids, items: ids.items.map(jobId => this.jobs.require(jobId)) };
  }
}

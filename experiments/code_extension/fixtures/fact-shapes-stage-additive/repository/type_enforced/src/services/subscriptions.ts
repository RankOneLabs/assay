import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { conflict, limitExceeded, missing } from "../domain/errors.ts";
import { sameFilters, subscriptionSchema, type Subscription } from "../domain/notifications.ts";
import { JobRepository } from "../repositories/jobs.ts";
import { SubscriptionRepository } from "../repositories/subscriptions.ts";
import { AccessService } from "./access.ts";

const maxSubscriptionsPerPrincipal = 50;

export class SubscriptionService {
  constructor(
    private readonly db: Database,
    private readonly subscriptions: SubscriptionRepository,
    private readonly jobs: JobRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  create(actor: Principal, input: unknown): Subscription {
    this.access.require(actor, readAccess);
    const parsed = subscriptionSchema.parse(input);
    const filters = { pattern: parsed.pattern, jobId: parsed.jobId ?? null, stage: parsed.stage ?? null };
    return this.db.transaction(() => {
      if (filters.jobId !== null) this.access.requireJob(actor, readAccess, this.jobs.require(filters.jobId));
      const existing = this.subscriptions.forPrincipal(actor.project, actor.id);
      if (existing.length >= maxSubscriptionsPerPrincipal) limitExceeded("subscription limit reached");
      const duplicate = existing.find(subscription => sameFilters(subscription, filters));
      if (duplicate) conflict("an identical subscription exists", { id: duplicate.id });
      return this.subscriptions.create({
        id: parsed.id,
        project: actor.project,
        principal: actor.id,
        ...filters,
      }, this.now());
    })();
  }

  list(actor: Principal): Subscription[] {
    this.access.require(actor, readAccess);
    return this.subscriptions.forPrincipal(actor.project, actor.id);
  }

  remove(actor: Principal, id: string): void {
    this.access.require(actor, readAccess);
    const subscription = this.subscriptions.get(id);
    // Another principal's subscription reads as missing so ids cannot be probed.
    if (!subscription || subscription.project !== actor.project || subscription.principal !== actor.id) {
      missing("subscription", id);
    }
    this.subscriptions.delete(id);
  }
}

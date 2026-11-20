import type { Database } from "bun:sqlite";
import { z } from "zod";
import type { Principal } from "../domain/models.ts";
import { readAccess } from "../domain/access_levels.ts";
import { conflict } from "../domain/errors.ts";
import { eventPayload, matchesSubscription } from "../domain/notifications.ts";
import {
  attemptOutcome, claimSchema, reportSchema, signedRequest, type WebhookDelivery,
} from "../domain/webhooks.ts";
import { OutboxRepository } from "../repositories/outbox.ts";
import { DeliveryRepository } from "../repositories/deliveries.ts";
import { NotificationRepository } from "../repositories/notifications.ts";
import { SubscriptionRepository } from "../repositories/subscriptions.ts";
import { WebhookRepository } from "../repositories/webhooks.ts";
import { GrantRepository } from "../repositories/grants.ts";
import { AccessService } from "./access.ts";

const collectSchema = z.object({ limit: z.number().int().min(1).max(500).default(200) }).strict();
const deadLetterSchema = z.object({ limit: z.coerce.number().int().min(1).max(100).default(25) }).strict();

/**
 * Fans job events out to subscribers and webhook endpoints. This service never makes a
 * network request: workers claim signed requests, send them, and report the answer.
 */
export class OutboxService {
  constructor(
    private readonly db: Database,
    private readonly outbox: OutboxRepository,
    private readonly deliveries: DeliveryRepository,
    private readonly notifications: NotificationRepository,
    private readonly subscriptions: SubscriptionRepository,
    private readonly webhooks: WebhookRepository,
    private readonly grants: GrantRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  /**
   * Enqueue notifications and deliveries for the project's events after its cursor, advancing
   * the cursor in the same transaction so no event is fanned out twice or skipped.
   */
  collect(actor: Principal, input: unknown) {
    this.access.require(actor, "case_admin");
    const { limit } = collectSchema.parse(input);
    return this.db.transaction(() => {
      const now = this.now();
      const after = this.outbox.cursor(actor.project);
      const batch = this.outbox.eventsAfter(actor.project, after, limit);
      // Subscribers who lost read access stop hearing about the project but keep their filters.
      const subscriptions = this.subscriptions.forProject(actor.project).filter(subscription =>
        this.grants.has({ id: subscription.principal, project: actor.project }, readAccess));
      const endpoints = this.webhooks.list(actor.project).filter(endpoint => endpoint.active);
      let notifications = 0;
      let deliveries = 0;
      for (const { event, job } of batch) {
        const payload = eventPayload(event, job);
        // Actors are not told about their own changes.
        for (const subscription of subscriptions) {
          if (subscription.principal === event.actor || !matchesSubscription(subscription, event, job.stage)) continue;
          const recipient = { id: subscription.principal, project: actor.project };
          if (this.notifications.insert(recipient, subscription.id, event, payload, now)) notifications++;
        }
        for (const endpoint of endpoints) {
          if (this.deliveries.enqueue(actor.project, endpoint.id, event, payload, now)) deliveries++;
        }
      }
      const cursor = batch.at(-1)?.event.sequence ?? after;
      this.outbox.advance(actor.project, cursor, actor.id, now);
      // A full batch means more events may be waiting for the next pass.
      return { events: batch.length, notifications, deliveries, cursor, more: batch.length === limit };
    })();
  }

  /** Lease due deliveries to a worker; a lease that lapses unreported makes them due again. */
  claim(actor: Principal, input: unknown) {
    this.access.require(actor, "case_admin");
    const parsed = claimSchema.parse(input);
    return this.db.transaction(() => {
      const now = this.now();
      const leaseExpiresAt = now + parsed.leaseMs;
      return this.deliveries.due(actor.project, now, parsed.limit).map(delivery => {
        const leaseToken = crypto.randomUUID();
        this.deliveries.lease(delivery.id, parsed.worker, leaseToken, leaseExpiresAt, now);
        const url = this.webhooks.require(delivery.webhookId).url;
        return {
          id: delivery.id,
          attempt: delivery.attempts + 1,
          leaseToken,
          leaseExpiresAt,
          request: signedRequest(url, this.webhooks.secret(delivery.webhookId), delivery, now),
        };
      });
    })();
  }

  /** Record the receiver's answer; failures retry on the policy's schedule, then dead-letter. */
  report(actor: Principal, id: number, input: unknown): WebhookDelivery {
    this.access.require(actor, "case_admin");
    const parsed = reportSchema.parse(input);
    return this.db.transaction(() => {
      const delivery = this.deliveries.require(actor.project, id);
      const now = this.now();
      if (!this.deliveries.leaseHeld(id, parsed.leaseToken, now)) {
        conflict("delivery is not leased under this token", { status: delivery.status });
      }
      this.deliveries.record(id, attemptOutcome(delivery.attempts, parsed.status, now), parsed.status, now);
      return this.deliveries.require(actor.project, id);
    })();
  }

  deadLetters(actor: Principal, input: unknown): WebhookDelivery[] {
    this.access.require(actor, "case_admin");
    return this.deliveries.deadLetters(actor.project, deadLetterSchema.parse(input).limit);
  }

  /** A dead letter goes back in line, due now, if its endpoint is still active. */
  redeliver(actor: Principal, id: number): WebhookDelivery {
    this.access.require(actor, "case_admin");
    return this.db.transaction(() => {
      const delivery = this.deliveries.require(actor.project, id);
      if (delivery.status !== "dead") conflict("only dead deliveries can be redelivered", { status: delivery.status });
      if (!this.webhooks.require(delivery.webhookId).active) conflict("webhook endpoint is inactive");
      this.deliveries.redeliver(id, this.now());
      return this.deliveries.require(actor.project, id);
    })();
  }
}

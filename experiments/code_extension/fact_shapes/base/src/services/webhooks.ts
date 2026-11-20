import type { Database } from "bun:sqlite";
import type { Principal } from "../domain/models.ts";
import { revisionSchema } from "../domain/validation.ts";
import { conflict, limitExceeded, missing } from "../domain/errors.ts";
import { createWebhookSchema, patchWebhookSchema, type WebhookEndpoint } from "../domain/webhooks.ts";
import { WebhookRepository } from "../repositories/webhooks.ts";
import { AccessService } from "./access.ts";

const maxEndpointsPerProject = 10;

/** The only responses that carry an endpoint's secret: creation and rotation. */
export interface IssuedSecret {
  endpoint: WebhookEndpoint;
  secret: string;
}

export class WebhookService {
  constructor(
    private readonly db: Database,
    private readonly webhooks: WebhookRepository,
    private readonly access: AccessService,
    private readonly now: () => number,
  ) {}

  create(actor: Principal, input: unknown): IssuedSecret {
    this.access.require(actor, "case_admin");
    const { id, ...fields } = createWebhookSchema.parse(input);
    return this.db.transaction(() => {
      const existing = this.webhooks.list(actor.project);
      if (existing.length >= maxEndpointsPerProject) limitExceeded("webhook endpoint limit reached");
      requireUnusedUrl(existing, fields.url);
      const secret = generateSecret();
      return { endpoint: this.webhooks.create(id, actor.project, fields, secret, this.now()), secret };
    })();
  }

  list(actor: Principal): WebhookEndpoint[] {
    this.access.require(actor, "case_admin");
    return this.webhooks.list(actor.project);
  }

  get(actor: Principal, id: string): WebhookEndpoint {
    this.access.require(actor, "case_admin");
    const endpoint = this.webhooks.get(id);
    if (!endpoint || endpoint.project !== actor.project) missing("webhook", id);
    return endpoint;
  }

  update(actor: Principal, id: string, input: unknown): WebhookEndpoint {
    this.access.require(actor, "case_admin");
    const parsed = patchWebhookSchema.parse(input);
    return this.db.transaction(() => {
      const current = this.get(actor, id);
      const url = parsed.url ?? current.url;
      requireUnusedUrl(this.webhooks.list(actor.project).filter(endpoint => endpoint.id !== id), url);
      const active = parsed.active ?? current.active;
      return this.webhooks.update(id, { url, active }, parsed.expectedRevision, this.now());
    })();
  }

  /** Deliveries claimed after a rotation are signed with the new secret. */
  rotate(actor: Principal, id: string, input: unknown): IssuedSecret {
    this.access.require(actor, "case_admin");
    const parsed = revisionSchema.parse(input);
    return this.db.transaction(() => {
      this.get(actor, id);
      const secret = generateSecret();
      return { endpoint: this.webhooks.rotate(id, secret, parsed.expectedRevision, this.now()), secret };
    })();
  }

  /** Removing an endpoint drops its deliveries, including any still waiting to go out. */
  remove(actor: Principal, id: string, input: unknown): void {
    this.access.require(actor, "case_admin");
    const parsed = revisionSchema.parse(input);
    this.db.transaction(() => {
      this.get(actor, id);
      this.webhooks.delete(id, parsed.expectedRevision);
    })();
  }
}

function requireUnusedUrl(endpoints: readonly WebhookEndpoint[], url: string): void {
  const existing = endpoints.find(endpoint => endpoint.url === url);
  if (existing) conflict("another webhook already uses this url", { id: existing.id });
}

function generateSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return `whsec_${Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("")}`;
}

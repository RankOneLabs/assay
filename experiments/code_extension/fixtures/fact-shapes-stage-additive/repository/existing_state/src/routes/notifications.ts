import { z } from "zod";
import type { Context, Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json } from "./http.ts";

/** Webhook deliveries have numeric ids. */
function deliveryId(c: Context): number {
  return z.coerce.number().int().positive().max(Number.MAX_SAFE_INTEGER).parse(c.req.param("id"));
}

export function registerNotificationRoutes(app: Hono, services: ServiceContext): void {
  app.post("/subscriptions", async c => {
    return c.json(services.subscriptions.create(principal(c), await json(c)), 201);
  });
  app.get("/subscriptions", c => c.json(services.subscriptions.list(principal(c))));
  app.delete("/subscriptions/:id", c => {
    services.subscriptions.remove(principal(c), identifier(c));
    return c.body(null, 204);
  });

  app.post("/webhooks", async c => {
    const issued = services.webhooks.create(principal(c), await json(c));
    c.header("location", `/webhooks/${issued.endpoint.id}`);
    return c.json(issued, 201);
  });
  app.get("/webhooks", c => c.json(services.webhooks.list(principal(c))));
  app.get("/webhooks/:id", c => {
    const endpoint = services.webhooks.get(principal(c), identifier(c));
    c.header("etag", `"${endpoint.revision}"`);
    return c.json(endpoint);
  });
  app.patch("/webhooks/:id", async c => {
    return c.json(services.webhooks.update(principal(c), identifier(c), await json(c)));
  });
  app.post("/webhooks/:id/rotate", async c => {
    return c.json(services.webhooks.rotate(principal(c), identifier(c), await json(c)));
  });
  app.delete("/webhooks/:id", async c => {
    services.webhooks.remove(principal(c), identifier(c), await json(c));
    return c.body(null, 204);
  });

  app.post("/outbox/collect", async c => {
    return c.json(services.outbox.collect(principal(c), await json(c)));
  });
  app.post("/outbox/claim", async c => {
    return c.json(services.outbox.claim(principal(c), await json(c)));
  });
  app.post("/outbox/deliveries/:id/report", async c => {
    return c.json(services.outbox.report(principal(c), deliveryId(c), await json(c)));
  });
  app.post("/outbox/deliveries/:id/redeliver", c => {
    return c.json(services.outbox.redeliver(principal(c), deliveryId(c)));
  });
  app.get("/outbox/dead", c => c.json(services.outbox.deadLetters(principal(c), c.req.query())));

  app.get("/notifications", c => c.json(services.notifications.inbox(principal(c), c.req.query())));
  app.get("/notifications/counts", c => c.json(services.notifications.counts(principal(c))));
  app.post("/notifications/read", async c => {
    return c.json(services.notifications.markRead(principal(c), await json(c)));
  });
}

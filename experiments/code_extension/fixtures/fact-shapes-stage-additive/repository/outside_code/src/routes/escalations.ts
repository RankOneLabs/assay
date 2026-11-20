import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json } from "./http.ts";

export function registerEscalationRoutes(app: Hono, services: ServiceContext): void {
  app.get("/escalation-rules", c => c.json(services.escalations.listRules(principal(c), c.req.query())));
  app.post("/escalation-rules", async c => {
    const rule = services.escalations.createRule(principal(c), await json(c));
    c.header("location", `/escalation-rules/${rule.id}`);
    return c.json(rule, 201);
  });
  app.get("/escalation-rules/:id", c => c.json(services.escalations.getRule(principal(c), identifier(c))));
  app.patch("/escalation-rules/:id", async c => {
    return c.json(services.escalations.updateRule(principal(c), identifier(c), await json(c)));
  });

  app.post("/escalations/evaluate", async c => {
    return c.json(services.escalations.evaluate(principal(c), await json(c)));
  });
  app.get("/escalations/summary", c => c.json(services.escalations.summary(principal(c))));
  app.get("/escalations", c => c.json(services.escalations.listOpen(principal(c), c.req.query())));
  app.get("/escalations/:id", c => c.json(services.escalations.get(principal(c), c.req.param("id"))));
  app.post("/escalations/:id/acknowledge", c => {
    return c.json(services.escalations.acknowledge(principal(c), c.req.param("id")));
  });
  app.post("/escalations/:id/resolve", async c => {
    return c.json(services.escalations.resolve(principal(c), c.req.param("id"), await json(c)));
  });
}

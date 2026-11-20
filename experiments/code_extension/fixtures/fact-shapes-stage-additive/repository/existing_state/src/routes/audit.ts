import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier } from "./http.ts";

export function registerAuditRoutes(app: Hono, services: ServiceContext): void {
  app.get("/audit/events", c => c.json(services.audit.events(principal(c), c.req.query())));
  app.get("/audit/summary", c => c.json(services.audit.summary(principal(c), c.req.query())));
  app.get("/audit/stages", c => c.json(services.audit.dwell(principal(c))));
  app.get("/audit/jobs/:id/stages", c => c.json(services.audit.stages(principal(c), identifier(c))));

  app.get("/audit/export", c => {
    const result = services.audit.export(principal(c), c.req.query());
    c.header("content-type", "application/x-ndjson; charset=utf-8");
    c.header("content-disposition", 'attachment; filename="audit.ndjson"');
    c.header("x-audit-count", String(result.count));
    if (result.nextCursor !== null) c.header("x-audit-next-cursor", String(result.nextCursor));
    return c.body(result.body);
  });
}

import { z } from "zod";
import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { grantSchema } from "../domain/validation.ts";
import { principal, identifier, json, integerQuery } from "./http.ts";

export function registerOperationRoutes(app: Hono, services: ServiceContext): void {
  app.post("/jobs/:id/builds", async c => {
    return c.json(services.builds.start(principal(c), identifier(c), await json(c)), 201);
  });

  app.get("/jobs/:id/builds", c => {
    return c.json(services.builds.list(principal(c), identifier(c)));
  });

  app.post("/jobs/:id/builds/finish", async c => {
    return c.json(services.builds.finish(principal(c), identifier(c), await json(c)));
  });

  app.delete("/jobs/:id/builds/:sessionId", c => {
    services.builds.end(principal(c), identifier(c), identifier(c, "sessionId"));
    return c.body(null, 204);
  });

  app.post("/jobs/:id/builds/:sessionId/cancel", async c => {
    const input = z.object({ reason: z.string() }).strict().parse(await json(c));
    return c.json(services.builds.cancel(principal(c), identifier(c), identifier(c, "sessionId"), input.reason));
  });
  app.post("/jobs/:id/builds/recover", async c => {
    const input = z.object({ reason: z.string() }).strict().parse(await json(c));
    return c.json(services.builds.recover(principal(c), identifier(c), input.reason));
  });
  app.get("/jobs/:id/builds/summary", c => c.json(services.builds.summary(principal(c), identifier(c))));
  app.get("/jobs/:id/builds/:attemptId/output", c => c.json(services.builds.output(
    principal(c), identifier(c), identifier(c, "attemptId"),
    integerQuery(c, "offset", 0, Number.MAX_SAFE_INTEGER),
    integerQuery(c, "limit", 4096, 10000),
  )));

  app.post("/grants/bulk", async c => {
    return c.json(services.access.bulkGrant(principal(c), await json(c)), 201);
  });
  app.delete("/grants/bulk", async c => {
    return c.json(services.access.bulkRevoke(principal(c), await json(c)));
  });
  app.get("/preferences/evidence-kind", c => {
    return c.json({ kind: services.evidence.getDefaultKind(principal(c)) });
  });
  app.put("/preferences/evidence-kind", async c => {
    const input = z.object({ kind: z.unknown() }).strict().parse(await json(c));
    services.evidence.setDefaultKind(principal(c), input.kind);
    return c.body(null, 204);
  });
  app.delete("/preferences/evidence-kind", c => {
    services.evidence.clearDefaultKind(principal(c));
    return c.body(null, 204);
  });
  app.get("/preferences/permission", c => {
    return c.json({ permission: services.access.getDefaultPermission(principal(c)) });
  });
  app.put("/preferences/permission", async c => {
    const input = z.object({ permission: z.unknown() }).strict().parse(await json(c));
    services.access.setDefaultPermission(principal(c), input.permission);
    return c.body(null, 204);
  });
  app.delete("/preferences/permission", c => {
    services.access.clearDefaultPermission(principal(c));
    return c.body(null, 204);
  });
  app.post("/grants/default/:principal", c => {
    return c.json(services.access.grantDefault(principal(c), identifier(c, "principal")), 201);
  });

  app.get("/grants/:principal", c => {
    return c.json(services.access.list(principal(c), identifier(c, "principal")));
  });

  app.post("/grants", async c => {
    const input = grantSchema.parse(await json(c));
    const actor = principal(c);
    if (input.project !== actor.project) return c.json({ error: "forbidden" }, 403);
    return c.json(services.access.grant(actor, input.principal, input.permission), 201);
  });

  app.post("/grants/peer", async c => {
    const input = grantSchema.parse(await json(c));
    const actor = principal(c);
    if (input.project !== actor.project) return c.json({ error: "forbidden" }, 403);
    return c.json(services.access.grantPeer(actor, input.principal, input.permission), 201);
  });

  app.delete("/grants", async c => {
    const input = grantSchema.parse(await json(c));
    const actor = principal(c);
    if (input.project !== actor.project) return c.json({ error: "forbidden" }, 403);
    return c.json({ revoked: services.access.revoke(actor, input.principal, input.permission) });
  });

  app.post("/imports/preview", async c => {
    return c.json(services.imports.preview(principal(c), await json(c)));
  });
  app.post("/imports/commit", async c => {
    const envelope = z.object({ input: z.unknown(), digest: z.string() }).strict().parse(await json(c));
    return c.json(services.imports.commit(principal(c), envelope.input, envelope.digest), 201);
  });
  app.post("/dispatch", async c => {
    const result = services.dispatch.next(principal(c), await json(c));
    return result ? c.json(result, 201) : c.body(null, 204);
  });
  app.get("/dispatch/capacity", c => c.json(services.dispatch.capacity(principal(c))));
  app.get("/dispatch/running", c => c.json(services.dispatch.running(principal(c))));

  app.get("/reports/summary", c => c.json(services.reports.summary(principal(c))));
  app.get("/reports/workloads", c => c.json(services.reports.workloads(principal(c))));
  app.get("/reports/outcomes", c => c.json(services.reports.outcomes(principal(c))));
  app.get("/reports/activity", c => c.json(services.reports.activity(
    principal(c),
    integerQuery(c, "since", 0, Number.MAX_SAFE_INTEGER),
    integerQuery(c, "limit", 100, 100),
  )));

  app.get("/exports", c => c.json(services.exports.project(principal(c))));
  app.get("/exports/csv", c => {
    c.header("content-type", "text/csv; charset=utf-8");
    c.header("content-disposition", 'attachment; filename="jobs.csv"');
    return c.body(services.exports.csv(principal(c)));
  });

  app.post("/maintenance/archive", async c => {
    return c.json({ archived: services.maintenance.archive(principal(c), await json(c)) });
  });
  app.post("/maintenance/purge", c => {
    return c.json({ purged: services.maintenance.purge(
      principal(c),
      integerQuery(c, "before", 0, Number.MAX_SAFE_INTEGER),
      integerQuery(c, "limit", 25, 100),
    ) });
  });
  app.get("/maintenance/integrity", c => c.json(services.maintenance.integrity(principal(c))));
  app.get("/maintenance/retention", c => c.json(services.maintenance.retention(principal(c))));
  app.put("/maintenance/retention", async c => {
    return c.json(services.maintenance.setRetention(principal(c), await json(c)));
  });
}

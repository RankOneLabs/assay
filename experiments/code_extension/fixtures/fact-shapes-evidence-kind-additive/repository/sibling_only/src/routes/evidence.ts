import { z } from "zod";
import { keySchema } from "../domain/validation.ts";
import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { mediaFor } from "../domain/transitions.ts";
import { principal, identifier, json } from "./http.ts";

export function registerEvidenceRoutes(app: Hono, services: ServiceContext): void {
  app.get("/jobs/:id/evidence/manifest", c => {
    return c.json(services.evidence.manifest(principal(c), identifier(c)));
  });
  app.get("/jobs/:id/evidence/verify", c => {
    return c.json(services.evidence.verify(principal(c), identifier(c)));
  });
  app.post("/jobs/:id/evidence/search", async c => {
    return c.json(services.evidence.search(principal(c), identifier(c), await json(c)));
  });
  app.post("/jobs/:id/evidence/bulk", async c => {
    return c.json(services.evidence.bulkAttach(principal(c), identifier(c), await json(c)), 201);
  });
  app.delete("/jobs/:id/evidence/bulk", async c => {
    return c.json(services.evidence.bulkRemove(principal(c), identifier(c), await json(c)));
  });
  app.post("/jobs/:id/evidence/:evidenceId/copy", async c => {
    const input = z.object({ jobId: keySchema, id: keySchema }).strict().parse(await json(c));
    return c.json(services.evidence.copy(
      principal(c), identifier(c), identifier(c, "evidenceId"), input.jobId, input.id,
    ), 201);
  });
  app.get("/jobs/:id/evidence/compare/:otherId", c => {
    return c.json(services.evidence.compare(principal(c), identifier(c), identifier(c, "otherId")));
  });

  app.get("/jobs/:id/evidence", c => {
    return c.json(services.evidence.list(principal(c), identifier(c), c.req.query("kind")));
  });

  app.post("/jobs/:id/evidence", async c => {
    const evidence = services.evidence.attach(principal(c), identifier(c), await json(c));
    c.header("location", `/jobs/${evidence.jobId}/evidence/${evidence.id}`);
    return c.json(evidence, 201);
  });

  app.post("/jobs/:id/evidence/peer", async c => {
    return c.json(services.evidence.attach(principal(c), identifier(c), await json(c), true), 201);
  });

  app.get("/jobs/:id/evidence/:evidenceId", c => {
    const item = services.evidence.get(principal(c), identifier(c), identifier(c, "evidenceId"));
    c.header("etag", `"${item.revision}"`);
    return c.json(item);
  });

  app.get("/jobs/:id/evidence/:evidenceId/content", c => {
    const item = services.evidence.get(principal(c), identifier(c), identifier(c, "evidenceId"));
    c.header("content-type", mediaFor(item.kind));
    c.header("x-content-type-options", "nosniff");
    c.header("etag", `"${item.checksum}"`);
    return c.body(item.content);
  });

  app.patch("/jobs/:id/evidence/:evidenceId", async c => {
    return c.json(services.evidence.patch(
      principal(c), identifier(c), identifier(c, "evidenceId"), await json(c),
    ));
  });

  app.delete("/jobs/:id/evidence/:evidenceId", async c => {
    return c.json(services.evidence.remove(
      principal(c), identifier(c), identifier(c, "evidenceId"), await json(c),
    ));
  });
}

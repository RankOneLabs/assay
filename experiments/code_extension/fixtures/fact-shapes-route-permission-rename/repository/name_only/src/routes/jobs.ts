import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json, integerQuery } from "./http.ts";

export function registerJobRoutes(app: Hono, services: ServiceContext): void {
  app.post("/jobs/bulk/patch", async c => {
    return c.json(services.jobs.bulkPatch(principal(c), await json(c)));
  });
  app.post("/jobs/bulk/stage", async c => {
    return c.json(services.jobs.bulkTransition(principal(c), await json(c)));
  });
  app.post("/jobs/:id/clone", async c => {
    return c.json(services.jobs.clone(principal(c), identifier(c), await json(c)), 201);
  });
  app.get("/jobs/:id/timeline", c => c.json(services.jobs.timeline(principal(c), identifier(c))));
  app.get("/jobs/:id/compare/:otherId", c => c.json(services.jobs.compare(
    principal(c), identifier(c), identifier(c, "otherId"),
  )));

  app.get("/jobs", c => c.json(services.jobs.list(principal(c), c.req.query())));

  app.post("/jobs", async c => {
    const job = services.jobs.create(principal(c), await json(c));
    c.header("location", `/jobs/${job.id}`);
    return c.json(job, 201);
  });

  app.get("/jobs/:id", c => {
    const job = services.jobs.get(principal(c), identifier(c));
    c.header("etag", `"${job.revision}"`);
    return c.json(job);
  });

  app.patch("/jobs/:id", async c => {
    return c.json(services.jobs.patch(principal(c), identifier(c), await json(c)));
  });

  app.post("/jobs/:id/stage", async c => {
    return c.json(services.jobs.transition(principal(c), identifier(c), await json(c)));
  });

  app.post("/jobs/:id/stage/peer", async c => {
    return c.json(services.jobs.transition(principal(c), identifier(c), await json(c), true));
  });

  app.post("/jobs/:id/archive", async c => {
    return c.json(services.jobs.archive(principal(c), identifier(c), await json(c)));
  });

  app.post("/jobs/:id/restore", async c => {
    return c.json(services.jobs.restore(principal(c), identifier(c), await json(c)));
  });

  app.get("/jobs/:id/events", c => {
    return c.json(services.jobs.history(
      principal(c),
      identifier(c),
      integerQuery(c, "after", 0, Number.MAX_SAFE_INTEGER),
      integerQuery(c, "limit", 100, 100),
    ));
  });

  app.get("/jobs/:id/bundle", c => {
    return c.json(services.exports.bundle(principal(c), identifier(c)));
  });
}

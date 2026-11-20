import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json } from "./http.ts";

export function registerDigestRoutes(app: Hono, services: ServiceContext): void {
  app.get("/digests/schedules", c => c.json(services.digests.listSchedules(principal(c))));
  app.post("/digests/schedules", async c => {
    return c.json(services.digests.createSchedule(principal(c), await json(c)), 201);
  });
  app.get("/digests/schedules/due", c => c.json(services.digests.due(principal(c), c.req.query())));
  app.patch("/digests/schedules/:id", async c => {
    return c.json(services.digests.updateSchedule(principal(c), identifier(c), await json(c)));
  });
  app.post("/digests/schedules/:id/generate", async c => {
    return c.json(services.digests.generate(principal(c), identifier(c), await json(c)), 201);
  });

  app.get("/digests", c => c.json(services.digests.listDigests(principal(c), c.req.query())));
  app.get("/digests/:id", c => c.json(services.digests.getDigest(principal(c), c.req.param("id"))));
}

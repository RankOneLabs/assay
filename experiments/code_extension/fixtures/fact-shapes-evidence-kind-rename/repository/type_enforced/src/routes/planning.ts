import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { z } from "zod";
import { keySchema } from "../domain/validation.ts";
import { principal, identifier, integerQuery, json } from "./http.ts";

const dependencySchema = z.object({ requiresId: keySchema }).strict();

export function registerPlanningRoutes(app: Hono, services: ServiceContext): void {
  app.get("/planning", c => c.json(services.planning.projectPlan(principal(c))));
  app.get("/planning/ready", c => c.json(services.planning.ready(
    principal(c), integerQuery(c, "limit", 25, 100),
  )));
  app.get("/jobs/:id/impact", c => c.json(services.planning.jobImpact(principal(c), identifier(c))));
  app.get("/jobs/:id/blockers", c => c.json(services.planning.blockers(principal(c), identifier(c))));
  app.post("/jobs/:id/dependencies", async c => {
    const input = dependencySchema.parse(await json(c));
    return c.json({ added: services.planning.add(principal(c), identifier(c), input.requiresId) }, 201);
  });
  app.delete("/jobs/:id/dependencies/:requiresId", c => {
    return c.json({ removed: services.planning.remove(
      principal(c), identifier(c), identifier(c, "requiresId"),
    ) });
  });
}

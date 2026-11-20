import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json } from "./http.ts";

export function registerRunRoutes(app: Hono, services: ServiceContext): void {
  app.get("/runs", c => c.json(services.runs.list(principal(c), c.req.query())));
  app.post("/runs", async c => {
    const run = services.runs.create(principal(c), await json(c));
    c.header("location", `/runs/${run.id}`);
    return c.json(run, 201);
  });
  app.get("/runs/:id", c => c.json(services.runs.get(principal(c), identifier(c))));
  app.get("/runs/:id/jobs", c => c.json(services.runs.jobs(principal(c), identifier(c))));
  app.get("/runs/:id/summary", c => c.json(services.runs.summary(principal(c), identifier(c))));
  app.post("/runs/:id/jobs", async c => {
    return c.json(services.runs.add(principal(c), identifier(c), await json(c)));
  });
}

import type { Hono, Context } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json, integerQuery } from "./http.ts";

function pageQuery(c: Context, fallback: number): [number, number] {
  return [integerQuery(c, "limit", fallback, 100), integerQuery(c, "offset", 0, Number.MAX_SAFE_INTEGER)];
}

export function registerTagRoutes(app: Hono, services: ServiceContext): void {
  app.get("/tags", c => c.json(services.tags.project(principal(c), ...pageQuery(c, 50))));
  app.post("/tags/rename", async c => c.json(services.tags.rename(principal(c), await json(c))));
  app.post("/tags/merge", async c => c.json(services.tags.merge(principal(c), await json(c))));

  app.get("/jobs/:id/tags", c => c.json(services.tags.list(principal(c), identifier(c))));
  app.post("/jobs/:id/tags", async c => {
    return c.json(services.tags.add(principal(c), identifier(c), await json(c)));
  });
  app.delete("/jobs/:id/tags/:tag", c => {
    return c.json(services.tags.remove(principal(c), identifier(c), c.req.param("tag")));
  });

  app.get("/searches", c => c.json(services.searches.list(principal(c), ...pageQuery(c, 50))));
  app.post("/searches", async c => {
    const search = services.searches.create(principal(c), await json(c));
    c.header("location", `/searches/${search.id}`);
    return c.json(search, 201);
  });
  app.get("/searches/:id", c => {
    const search = services.searches.get(principal(c), identifier(c));
    c.header("etag", `"${search.revision}"`);
    return c.json(search);
  });
  app.patch("/searches/:id", async c => {
    return c.json(services.searches.update(principal(c), identifier(c), await json(c)));
  });
  app.delete("/searches/:id", async c => {
    return c.json(services.searches.remove(principal(c), identifier(c), await json(c)));
  });
  app.get("/searches/:id/run", c => {
    return c.json(services.searches.run(principal(c), identifier(c), ...pageQuery(c, 25)));
  });
}

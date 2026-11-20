import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, json, integerQuery } from "./http.ts";

export function registerSettingsRoutes(app: Hono, services: ServiceContext): void {
  app.get("/settings", c => {
    const settings = services.settings.get(principal(c));
    c.header("etag", `"${settings.revision}"`);
    return c.json(settings);
  });
  app.patch("/settings", async c => c.json(services.settings.update(principal(c), await json(c))));
  app.get("/settings/history", c => c.json(services.settings.history(
    principal(c),
    integerQuery(c, "after", 0, Number.MAX_SAFE_INTEGER),
    integerQuery(c, "limit", 50, 100),
  )));

  app.get("/usage", c => c.json(services.usage.report(principal(c))));
  app.get("/usage/stale", c => c.json(services.usage.stale(
    principal(c),
    integerQuery(c, "limit", 25, 100),
    integerQuery(c, "offset", 0, Number.MAX_SAFE_INTEGER),
  )));
}

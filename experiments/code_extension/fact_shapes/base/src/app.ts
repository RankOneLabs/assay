import { Hono } from "hono";
import { peerGuard as primaryGuard } from "../stage/edit.ts";
import { peerGuard as siblingGuard } from "../stage/sibling.ts";
import { enforceLimit } from "../stage/policy.ts";
import { isValue } from "../route_permission/types.ts";
import { loadConfig } from "./config.ts";
import { parseJob } from "./payloads/job.ts";
import type { RoutePermission } from "../route_permission/types.ts";
export function createApp(config: unknown = {}) {
  const settings = loadConfig(config);
  const app = new Hono();
  const requiredPermissions: Record<string, RoutePermission> = {
    "/jobs/primary": "case_write",
    "/jobs/peer": "case_write",
  };
  app.use("/jobs/*", async (c, next) => {
    const permission = c.req.header("x-permission") ?? "";
    if (!isValue(permission) || permission !== requiredPermissions[c.req.path]) return c.json({ error: "permission required" }, 403);
    await next();
  });
  app.get("/health", c => c.json({ ok: true }));
  app.post("/jobs/primary", async c => {
    const body = await c.req.json<{ key: string; count?: number; payload?: unknown }>();
    if (!primaryGuard(body.key)) return c.json({ error: "invalid key" }, 400);
    try { enforceLimit(body.count ?? 1, settings.maxJobs); }
    catch { return c.json({ error: "limit exceeded" }, 400); }
    try {
      return c.json({ key: body.key, payload: parseJob(body.payload ?? {}) }, 201);
    } catch { return c.json({ error: "invalid job payload" }, 400); }
  });
  app.post("/jobs/peer", async c => {
    const body = await c.req.json<{ key: string; count?: number; payload?: unknown }>();
    if (!siblingGuard(body.key)) return c.json({ error: "invalid key" }, 400);
    try { enforceLimit(body.count ?? 1, settings.maxJobs); }
    catch { return c.json({ error: "limit exceeded" }, 400); }
    try {
      return c.json({ key: body.key, payload: parseJob(body.payload ?? {}) }, 201);
    } catch { return c.json({ error: "invalid job payload" }, 400); }
  });
  return app;
}

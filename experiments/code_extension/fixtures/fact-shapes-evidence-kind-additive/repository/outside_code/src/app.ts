import { Hono } from "hono";
import { ServiceContext } from "./context.ts";
import { registerJobRoutes } from "./routes/jobs.ts";
import { registerEvidenceRoutes } from "./routes/evidence.ts";
import { registerOperationRoutes } from "./routes/operations.ts";
import { registerPlanningRoutes } from "./routes/planning.ts";
import { handleError } from "./routes/http.ts";

/** Dependency injection keeps requests and tests off the network. */
export function createApp(config: unknown = {}, context?: ServiceContext) {
  const services = context ?? new ServiceContext(config);
  const app = new Hono();
  app.onError(handleError);
  app.get("/health", c => c.json({ ok: true }));
  registerJobRoutes(app, services);
  registerEvidenceRoutes(app, services);
  registerOperationRoutes(app, services);
  registerPlanningRoutes(app, services);
  app.notFound(c => c.json({ error: "not_found" }, 404));
  return app;
}

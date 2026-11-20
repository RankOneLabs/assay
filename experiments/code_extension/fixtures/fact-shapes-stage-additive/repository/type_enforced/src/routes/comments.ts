import type { Hono } from "hono";
import type { ServiceContext } from "../context.ts";
import { principal, identifier, json } from "./http.ts";

export function registerCommentRoutes(app: Hono, services: ServiceContext): void {
  app.get("/jobs/:id/comments", c => c.json(services.comments.thread(principal(c), identifier(c))));

  app.post("/jobs/:id/comments", async c => {
    const comment = services.comments.add(principal(c), identifier(c), await json(c));
    c.header("location", `/jobs/${comment.jobId}/comments/${comment.id}`);
    return c.json(comment, 201);
  });

  app.get("/jobs/:id/comments/:commentId", c => {
    const comment = services.comments.get(principal(c), identifier(c), identifier(c, "commentId"));
    c.header("etag", `"${comment.revision}"`);
    return c.json(comment);
  });

  app.get("/jobs/:id/comments/:commentId/history", c => {
    return c.json(services.comments.history(principal(c), identifier(c), identifier(c, "commentId")));
  });

  app.patch("/jobs/:id/comments/:commentId", async c => {
    return c.json(services.comments.edit(
      principal(c), identifier(c), identifier(c, "commentId"), await json(c),
    ));
  });

  app.delete("/jobs/:id/comments/:commentId", async c => {
    return c.json(services.comments.remove(
      principal(c), identifier(c), identifier(c, "commentId"), await json(c),
    ));
  });

  app.get("/mentions", c => c.json(services.comments.mentions(principal(c), c.req.query())));
  app.post("/mentions/read", async c => c.json(services.comments.markMentions(principal(c), await json(c))));
  app.post("/mentions/read-all", c => c.json(services.comments.markAllRead(principal(c))));
}

import { expect } from "bun:test";
import { ServiceContext } from "../../src/context.ts";
import { createApp } from "../../src/app.ts";
import { values as permissions } from "../../route_permission/types.ts";
import type { Job, Evidence, Principal } from "../../src/domain/models.ts";

export const admin: Principal = { id: "admin", project: "project" };
export const reader: Principal = { id: "reader", project: "project" };
export const writer: Principal = { id: "writer", project: "project" };
export const outsider: Principal = { id: "outsider", project: "other" };

/** Every test owns an isolated real SQLite database and a deterministic clock. */
export function fixture(config: unknown = {}) {
  let timestamp = 1000;
  const context = new ServiceContext(config, () => timestamp++);
  for (const permission of permissions) {
    context.grantRepository.grant(admin, permission, "bootstrap", 0);
    context.grantRepository.grant(outsider, permission, "bootstrap", 0);
  }
  context.grantRepository.grant(reader, "case_read", "bootstrap", 0);
  context.grantRepository.grant(writer, "case_write", "bootstrap", 0);
  const app = createApp({}, context);
  return {
    context,
    app,
    create(id = "job", overrides: Record<string, unknown> = {}): Job {
      return context.jobs.create(admin, {
        id,
        title: `Job ${id}`,
        description: "A service integration job",
        owner: "owner",
        project: admin.project,
        ...overrides,
      });
    },
    attach(id = "evidence", jobId = "job", overrides: Record<string, unknown> = {}): Evidence {
      return context.evidence.attach(admin, jobId, {
        id,
        kind: "document",
        title: `Evidence ${id}`,
        content: `Content ${id}`,
        author: admin.id,
        ...overrides,
      });
    },
    async request(method: string, path: string, body?: unknown, actor: Principal = admin) {
      return app.request(path, {
        method,
        headers: {
          "content-type": "application/json",
          "x-principal": actor.id,
          "x-project": actor.project,
        },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    },
    [Symbol.dispose]() { context.close(); },
  };
}

export async function expectError(response: Response, status: number, code?: string) {
  expect(response.status).toBe(status);
  const body = await response.json() as { error: string };
  if (code) expect(body.error).toBe(code);
  expect(body.error).toBeString();
}

/** Populate historical rows without changing the configured live-job capacity. */
export function seedArchives(context: ServiceContext, count: number, project = admin.project) {
  context.db.transaction(() => {
    for (let index = 0; index < count; index++) {
      const id = `archive-${project}-${index}`;
      context.jobRepository.create({
        id, title: id, description: "Historical job", owner: "owner", project, priority: 0,
      }, "queued", 1);
      context.jobRepository.archive(id, 1, 2);
    }
  })();
}

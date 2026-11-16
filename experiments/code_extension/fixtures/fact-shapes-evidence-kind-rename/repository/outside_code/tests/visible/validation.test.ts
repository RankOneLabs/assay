import { describe, expect, test } from "bun:test";
import {
  createJobSchema,
  patchJobSchema,
  transitionSchema,
  evidenceSchema,
  patchEvidenceSchema,
  buildSchema,
  finishSchema,
  filterSchema,
  grantSchema,
  bulkSchema,
} from "../../src/domain/validation.ts";
import { fixture, admin } from "./helpers.ts";

const job = { id: "job", title: "Title", owner: "owner", project: "project" };
const evidence = { id: "proof", kind: "document" as const, title: "Proof", content: "Content", author: "author" };

describe("job-specific payload contracts", () => {
  test("creation normalizes titles and fills service defaults", () => {
    expect(createJobSchema.parse({ ...job, title: "  Title  " })).toEqual({
      ...job, description: "", priority: 0,
    });
    expect(createJobSchema.parse({ ...job, description: "" }).description).toBe("");
    expect(createJobSchema.parse({ ...job, priority: 100 }).priority).toBe(100);
  });

  test("creation refuses unknown fields that could bypass stage ownership", () => {
    expect(() => createJobSchema.parse({ ...job, stage: "complete" })).toThrow();
    expect(() => createJobSchema.parse({ ...job, revision: 999 })).toThrow();
    expect(() => createJobSchema.parse({ ...job, archivedAt: 1 })).toThrow();
    expect(() => createJobSchema.parse({ ...job, createdAt: 1 })).toThrow();
  });

  test("ids and principals have identifier rather than free-text semantics", () => {
    expect(() => createJobSchema.parse({ ...job, id: "bad/id" })).toThrow();
    expect(() => createJobSchema.parse({ ...job, owner: "bad owner" })).toThrow();
    expect(() => createJobSchema.parse({ ...job, project: "" })).toThrow();
    expect(createJobSchema.parse({ ...job, id: "a_1-B" }).id).toBe("a_1-B");
  });

  test("priority must be an integer in the service range", () => {
    expect(() => createJobSchema.parse({ ...job, priority: -1 })).toThrow();
    expect(() => createJobSchema.parse({ ...job, priority: 101 })).toThrow();
    expect(() => createJobSchema.parse({ ...job, priority: 1.5 })).toThrow();
    expect(() => createJobSchema.parse({ ...job, priority: "5" })).toThrow();
    expect(() => createJobSchema.parse({ ...job, priority: Infinity })).toThrow();
  });

  test("patch is restricted to mutable metadata and a revision precondition", () => {
    expect(patchJobSchema.parse({ title: "Changed", expectedRevision: 1 })).toEqual({ title: "Changed", expectedRevision: 1 });
    expect(() => patchJobSchema.parse({ title: "Changed" })).toThrow();
    expect(() => patchJobSchema.parse({ title: "Changed", expectedRevision: 0 })).toThrow();
    expect(() => patchJobSchema.parse({ stage: "active", expectedRevision: 1 })).toThrow();
    expect(() => patchJobSchema.parse({ project: "other", expectedRevision: 1 })).toThrow();
  });

  test("transitions require a known stage, a reason and a current-shaped revision", () => {
    expect(transitionSchema.parse({ stage: "active", reason: "  start  ", expectedRevision: 1 }).reason).toBe("start");
    expect(() => transitionSchema.parse({ stage: "triaged", reason: "start", expectedRevision: 1 })).toThrow();
    expect(() => transitionSchema.parse({ stage: "active", reason: " ", expectedRevision: 1 })).toThrow();
    expect(() => transitionSchema.parse({ stage: "active", reason: "start", expectedRevision: -1 })).toThrow();
    expect(() => transitionSchema.parse({ stage: "active", expectedRevision: 1 })).toThrow();
  });

  test("evidence requires content, authorship and an inventoried kind", () => {
    expect(evidenceSchema.parse(evidence)).toEqual(evidence);
    expect(() => evidenceSchema.parse({ ...evidence, content: "" })).toThrow();
    expect(() => evidenceSchema.parse({ ...evidence, author: "" })).toThrow();
    expect(() => evidenceSchema.parse({ ...evidence, kind: "attestation" })).toThrow();
    expect(() => evidenceSchema.parse({ ...evidence, checksum: "pretend" })).toThrow();
  });

  test("evidence editing cannot silently reclassify the original attachment", () => {
    expect(patchEvidenceSchema.parse({ title: "Changed", expectedRevision: 1 }).title).toBe("Changed");
    expect(() => patchEvidenceSchema.parse({ kind: "image", expectedRevision: 1 })).toThrow();
    expect(() => patchEvidenceSchema.parse({ author: "other", expectedRevision: 1 })).toThrow();
    expect(() => patchEvidenceSchema.parse({ expectedRevision: 1 })).toThrow();
  });

  test("build start requires explicit session and worker identities", () => {
    const valid = { id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1 };
    expect(buildSchema.parse(valid)).toEqual(valid);
    expect(() => buildSchema.parse({ ...valid, sessionId: "" })).toThrow();
    expect(() => buildSchema.parse({ ...valid, worker: "bad/worker" })).toThrow();
    expect(() => buildSchema.parse({ ...valid, running: true })).toThrow();
  });

  test("build completion uses bounded process exit codes", () => {
    const valid = { sessionId: "session", exitCode: 0, output: "done" };
    expect(finishSchema.parse(valid)).toEqual(valid);
    expect(finishSchema.parse({ ...valid, exitCode: 255 }).exitCode).toBe(255);
    expect(() => finishSchema.parse({ ...valid, exitCode: -1 })).toThrow();
    expect(() => finishSchema.parse({ ...valid, exitCode: 256 })).toThrow();
    expect(() => finishSchema.parse({ ...valid, exitCode: 0.5 })).toThrow();
    expect(() => finishSchema.parse({ ...valid, output: "x".repeat(100001) })).toThrow();
  });

  test("query-string coercion does not apply to write payloads", () => {
    expect(filterSchema.parse({ limit: "10", offset: "2", minPriority: "8" })).toMatchObject({
      limit: 10, offset: 2, minPriority: 8,
    });
    expect(() => createJobSchema.parse({ ...job, priority: "8" })).toThrow();
    expect(() => patchJobSchema.parse({ title: "Changed", expectedRevision: "1" })).toThrow();
  });

  test("grant mutation requires an inventoried permission and a project", () => {
    const valid = { principal: "user", permission: "case_read" as const, project: "project" };
    expect(grantSchema.parse(valid)).toEqual(valid);
    expect(() => grantSchema.parse({ ...valid, permission: "case_inspect" })).toThrow();
    expect(() => grantSchema.parse({ principal: "user", permission: "case_read" })).toThrow();
    expect(() => grantSchema.parse({ ...valid, grantedBy: "spoofed" })).toThrow();
  });

  test("bulk mutation requires nonempty unique identifiers and an audit reason", () => {
    expect(bulkSchema.parse({ ids: ["a", "b"], reason: "  done  " }).reason).toBe("done");
    expect(() => bulkSchema.parse({ ids: [], reason: "done" })).toThrow();
    expect(() => bulkSchema.parse({ ids: ["a", "a"], reason: "done" })).toThrow();
    expect(() => bulkSchema.parse({ ids: ["a"], reason: "" })).toThrow();
    expect(() => bulkSchema.parse({ ids: ["bad/id"], reason: "done" })).toThrow();
  });

  test("parsing does not mutate caller-owned input objects", () => {
    using f = fixture();
    const input = { ...job, title: "  Original  " };
    const copy = structuredClone(input);
    const created = f.context.jobs.create(admin, input);
    expect(created.title).toBe("Original");
    expect(input).toEqual(copy);
    const patch = { title: "  Changed  ", expectedRevision: 1 };
    f.context.jobs.patch(admin, "job", patch);
    expect(patch.title).toBe("  Changed  ");
    expect(f.context.jobRepository.require("job").title).toBe("Changed");
  });
});

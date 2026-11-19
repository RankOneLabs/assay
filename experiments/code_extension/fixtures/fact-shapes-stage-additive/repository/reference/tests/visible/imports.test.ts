import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, expectError } from "./helpers.ts";

function input() {
  return {
    version: 1,
    entries: [
      {
        job: { id: "first", title: "First", owner: "owner", project: "project" },
        evidence: [{ id: "proof", title: "Proof", kind: "testimony", content: "First proof", author: "author" }],
      },
      {
        job: { id: "second", title: "Second", owner: "owner", project: "project" },
        evidence: [{ id: "image", title: "Image", kind: "image", content: "Image bytes", author: "author" }],
      },
    ],
  };
}

describe("atomic job and evidence import", () => {
  test("preview validates and hashes the normalized input without persistence", () => {
    using f = fixture();
    const preview = f.context.imports.preview(writer, input());
    expect(preview.jobs).toBe(2);
    expect(preview.evidence).toBe(2);
    expect(preview.issues).toEqual([]);
    expect(preview.digest).toHaveLength(64);
    expect(f.context.jobRepository.count()).toBe(0);
    expect(f.context.evidenceRepository.get("proof")).toBeNull();
    expect(f.context.imports.validate(writer, input())).toBe(true);
  });

  test("commit applies all jobs and evidence through normal domain operations", () => {
    using f = fixture();
    const source = input();
    const preview = f.context.imports.preview(admin, source);
    const created = f.context.imports.commit(admin, source, preview.digest);
    expect(created.map(job => job.id)).toEqual(["first", "second"]);
    expect(created.every(job => job.revision === 1)).toBe(true);
    expect(f.context.evidenceRepository.require("proof").kind).toBe("testimony");
    expect(f.context.evidenceRepository.require("image").kind).toBe("image");
    expect(f.context.eventRepository.count("first")).toBe(2);
    expect(f.context.eventRepository.count("second")).toBe(2);
  });

  test("changing source after preview invalidates the digest", () => {
    using f = fixture();
    const source = input();
    const preview = f.context.imports.preview(admin, source);
    source.entries[0]!.job.title = "Changed after review";
    expect(() => f.context.imports.commit(admin, source, preview.digest)).toThrow("changed since preview");
    expect(f.context.jobRepository.count()).toBe(0);
    expect(f.context.evidenceRepository.get("proof")).toBeNull();
  });

  test("preview reports duplicate job ids both in input and existing storage", () => {
    using f = fixture();
    f.create("first");
    const source = input();
    source.entries[1]!.job.id = "first";
    const preview = f.context.imports.preview(admin, source);
    expect(preview.issues.filter(issue => issue.message === "job id already exists")).toHaveLength(2);
    expect(f.context.imports.validate(admin, source)).toBe(false);
    expect(() => f.context.imports.commit(admin, source, preview.digest)).toThrow("preview has issues");
    expect(f.context.jobRepository.count()).toBe(1);
  });

  test("preview reports duplicate evidence ids across different jobs", () => {
    using f = fixture();
    const source = input();
    source.entries[1]!.evidence[0]!.id = "proof";
    const preview = f.context.imports.preview(admin, source);
    expect(preview.issues).toMatchObject([{ entry: 1, id: "proof", message: "evidence id already exists" }]);
    expect(() => f.context.imports.commit(admin, source, preview.digest)).toThrow("preview has issues");
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("repeated content in one job is rejected while cross-job reuse remains valid", () => {
    using f = fixture();
    const source = input();
    source.entries[0]!.evidence.push({
      id: "duplicate", title: "Copy", kind: "testimony", content: "First proof", author: "author",
    });
    const preview = f.context.imports.preview(admin, source);
    expect(preview.issues.some(issue => issue.message === "duplicate evidence content in job")).toBe(true);
    source.entries[0]!.evidence.pop();
    source.entries[1]!.evidence[0]!.content = "First proof";
    expect(f.context.imports.preview(admin, source).issues).toEqual([]);
  });

  test("existing evidence id collisions are discovered before commit", () => {
    using f = fixture();
    f.create("existing");
    f.attach("proof", "existing");
    const preview = f.context.imports.preview(admin, input());
    expect(preview.issues.some(issue => issue.id === "proof" && issue.message.includes("already exists"))).toBe(true);
    expect(f.context.jobRepository.count()).toBe(1);
    expect(f.context.evidenceRepository.require("proof").jobId).toBe("existing");
  });

  test("configured job, attachment and byte budgets are applied during preview", () => {
    using f = fixture({ maxJobs: 1, maxEvidence: 1, maxEvidenceBytes: 3 });
    const source = input();
    source.entries[0]!.evidence.push({
      id: "another", title: "Another", kind: "testimony", content: "Long proof", author: "author",
    });
    const preview = f.context.imports.preview(admin, source);
    expect(preview.issues.some(issue => issue.message === "project job limit reached")).toBe(true);
    expect(preview.issues.some(issue => issue.message === "evidence count limit reached")).toBe(true);
    expect(preview.issues.some(issue => issue.message === "evidence byte limit exceeded")).toBe(true);
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("bulk limits and source versions are validated without partial inserts", () => {
    using f = fixture({ maxBulkJobs: 1 });
    expect(() => f.context.imports.preview(admin, input())).toThrow("import job limit");
    expect(() => f.context.imports.preview(admin, { version: 2, entries: [] })).toThrow();
    expect(() => f.context.imports.preview(admin, { version: 1, entries: [] })).toThrow();
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("preview cannot disclose foreign-project id collisions", () => {
    using f = fixture();
    const source = input();
    source.entries[0]!.job.project = "other";
    expect(() => f.context.imports.preview(admin, source)).toThrow("project mismatch");
    expect(() => f.context.imports.preview(reader, source)).toThrow("permission");
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("a late event failure rolls back an entire nested import transaction", () => {
    using f = fixture();
    const source = input();
    const preview = f.context.imports.preview(admin, source);
    f.context.db.exec(`
      CREATE TRIGGER fail_second BEFORE INSERT ON job_events
      WHEN NEW.job_id = 'second' BEGIN SELECT RAISE(ABORT, 'second job failure'); END;
    `);
    expect(() => f.context.imports.commit(admin, source, preview.digest)).toThrow("second job failure");
    expect(f.context.jobRepository.get("first")).toBeNull();
    expect(f.context.jobRepository.get("second")).toBeNull();
    expect(f.context.evidenceRepository.get("proof")).toBeNull();
    expect(f.context.eventRepository.count("first")).toBe(0);
  });

  test("preview is rechecked at commit if another job consumed capacity", () => {
    using f = fixture({ maxJobs: 2 });
    const source = input();
    const preview = f.context.imports.preview(admin, source);
    expect(preview.issues).toEqual([]);
    f.create("interloper");
    expect(() => f.context.imports.commit(admin, source, preview.digest)).toThrow("preview has issues");
    expect(f.context.jobRepository.count()).toBe(1);
    expect(f.context.jobRepository.get("first")).toBeNull();
  });

  test("HTTP preview and commit retain the reviewed digest contract", async () => {
    using f = fixture();
    const source = input();
    const preview = await f.request("POST", "/imports/preview", source, writer);
    expect(preview.status).toBe(200);
    const body = await preview.json() as { digest: string; jobs: number };
    expect(body.jobs).toBe(2);
    await expectError(await f.request("POST", "/imports/commit", {
      input: source, digest: "incorrect",
    }, writer), 409);
    const committed = await f.request("POST", "/imports/commit", {
      input: source, digest: body.digest,
    }, writer);
    expect(committed.status).toBe(201);
    expect(await committed.json()).toMatchObject([{ id: "first" }, { id: "second" }]);
  });
});

describe("import normalization and shape boundaries", () => {
  test("equivalent defaulted payloads have the same preview digest", () => {
    using f = fixture();
    const implicit = input();
    const explicit = {
      ...implicit,
      entries: implicit.entries.map(entry => ({
        ...entry,
        job: { ...entry.job, description: "", priority: 0 },
      })),
    };
    const left = f.context.imports.preview(admin, implicit);
    const right = f.context.imports.preview(admin, explicit);
    expect(left.digest).toBe(right.digest);
    const committed = f.context.imports.commit(admin, explicit, left.digest);
    expect(committed).toHaveLength(2);
    expect(committed.every(job => job.description === "" && job.priority === 0)).toBe(true);
  });

  test("imports cannot inject completion, archive or revision fields", () => {
    using f = fixture();
    const source = input();
    const injected = {
      ...source,
      entries: [{ ...source.entries[0], job: { ...source.entries[0]!.job, stage: "complete" } }],
    };
    expect(() => f.context.imports.preview(admin, injected)).toThrow();
    const archived = {
      ...source,
      entries: [{ ...source.entries[0], job: { ...source.entries[0]!.job, archivedAt: 1000 } }],
    };
    expect(() => f.context.imports.preview(admin, archived)).toThrow();
    expect(f.context.jobRepository.count()).toBe(0);
  });

  test("unknown evidence kinds fail import validation before any job is created", () => {
    using f = fixture();
    const source = input();
    source.entries[1]!.evidence[0]!.kind = "unsupported_future";
    expect(() => f.context.imports.preview(admin, source)).toThrow();
    expect(() => f.context.imports.commit(admin, source, "ignored")).toThrow();
    expect(f.context.jobRepository.get("first")).toBeNull();
    expect(f.context.jobRepository.get("second")).toBeNull();
    expect(f.context.evidenceRepository.get("proof")).toBeNull();
  });

  test("successful imports do not share mutable input references with returned jobs", () => {
    using f = fixture();
    const source = input();
    const preview = f.context.imports.preview(admin, source);
    const jobs = f.context.imports.commit(admin, source, preview.digest);
    source.entries[0]!.job.title = "Changed input";
    jobs[0]!.title = "Changed return value";
    expect(f.context.jobRepository.require("first").title).toBe("First");
    expect(f.context.evidenceRepository.require("proof").content).toBe("First proof");
    expect(f.context.eventRepository.count("first")).toBe(2);
  });

  test("commit rejects a replay rather than quietly replacing imported jobs", () => {
    using f = fixture();
    const source = input();
    const preview = f.context.imports.preview(admin, source);
    f.context.imports.commit(admin, source, preview.digest);
    expect(() => f.context.imports.commit(admin, source, preview.digest)).toThrow("preview has issues");
    expect(f.context.jobRepository.count()).toBe(2);
    expect(f.context.eventRepository.count("first")).toBe(2);
    expect(f.context.eventRepository.count("second")).toBe(2);
  });
});

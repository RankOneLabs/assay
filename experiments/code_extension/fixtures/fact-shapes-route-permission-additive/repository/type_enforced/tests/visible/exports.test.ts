import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider } from "./helpers.ts";
import { checksum } from "../../src/domain/checksum.ts";

describe("consistent exports", () => {
  test("bundle joins a job with its own evidence and ordered history", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.attach("local", "first");
    f.attach("other", "second");
    const bundle = f.context.exports.bundle(reader, "first");
    expect(bundle.job.id).toBe("first");
    expect(bundle.evidence.map(item => item.id)).toEqual(["local"]);
    expect(bundle.events.map(event => event.action)).toEqual(["job.created", "evidence.attached"]);
    expect(bundle.events.every(event => event.jobId === "first")).toBe(true);
    expect(bundle.attempts).toEqual([]);
  });

  test("project export includes only authorized project data", () => {
    using f = fixture();
    f.create();
    f.context.jobs.create(outsider, { id: "foreign", title: "Foreign", owner: "owner", project: "other" });
    const document = f.context.exports.project(reader);
    expect(document.project).toBe("project");
    expect(document.version).toBe(1);
    expect(document.jobs.map(bundle => bundle.job.id)).toEqual(["job"]);
    expect(f.context.exports.verify(document)).toBe(true);
    const foreign = f.context.exports.project(outsider);
    expect(foreign.jobs.map(bundle => bundle.job.id)).toEqual(["foreign"]);
  });

  test("archives are omitted by default and included on explicit request", () => {
    using f = fixture();
    f.create("live");
    f.create("archived");
    f.context.jobs.archive(admin, "archived", { expectedRevision: 1 });
    expect(f.context.exports.project(reader).jobs.map(bundle => bundle.job.id)).toEqual(["live"]);
    const all = f.context.exports.project(reader, true);
    expect(all.jobs).toHaveLength(2);
    expect(all.jobs.find(bundle => bundle.job.id === "archived")?.job.archivedAt).not.toBeNull();
  });

  test("digest covers metadata, evidence and generation time", () => {
    using f = fixture();
    f.create();
    f.attach();
    const original = f.context.exports.project(reader);
    expect(f.context.exports.verify(original)).toBe(true);
    const changed = structuredClone(original);
    changed.generatedAt++;
    expect(f.context.exports.verify(changed)).toBe(false);
    const changedTitle = structuredClone(original);
    changedTitle.jobs[0]!.job.title = "tampered";
    expect(f.context.exports.verify(changedTitle)).toBe(false);
    expect(() => f.context.exports.requireVerified(changedTitle)).toThrow("integrity");
  });

  test("inner evidence digests are checked even if the outer digest is replaced", () => {
    using f = fixture();
    f.create();
    f.attach();
    const changed = f.context.exports.project(reader);
    changed.jobs[0]!.evidence[0]!.content = "tampered content";
    const { digest: ignored, ...data } = changed;
    expect(ignored).toBeString();
    changed.digest = checksum(JSON.stringify(data));
    expect(f.context.exports.verify(changed)).toBe(false);
  });

  test("export rejects bundles whose project ownership was altered", () => {
    using f = fixture();
    f.create();
    const changed = f.context.exports.project(reader);
    changed.jobs[0]!.job.project = "foreign";
    const { digest: previous, ...data } = changed;
    expect(previous).toBeString();
    changed.digest = checksum(JSON.stringify(data));
    expect(f.context.exports.verify(changed)).toBe(false);
  });

  test("unknown export versions fail integrity validation", () => {
    using f = fixture();
    const document = f.context.exports.project(reader);
    document.version = 2;
    expect(f.context.exports.verify(document)).toBe(false);
  });

  test("export limits reject truncation instead of silently losing jobs", () => {
    using f = fixture({ maxExportJobs: 1 });
    f.create("first");
    f.create("second");
    expect(() => f.context.exports.project(reader)).toThrow("export exceeds");
    expect(f.context.jobRepository.count()).toBe(2);
    expect(f.context.exports.bundle(reader, "first").job.id).toBe("first");
  });

  test("CSV escapes quotes, commas, newlines and spreadsheet formulas", () => {
    using f = fixture();
    f.create("comma", { title: 'A, "quoted" job' });
    f.create("formula", { title: "=SUM(A1:A2)" });
    f.create("newline", { title: "First\nSecond" });
    const csv = f.context.exports.csv(reader);
    expect(csv).toStartWith('"id","title","stage","owner","priority","revision"\r\n');
    expect(csv).toContain('"A, ""quoted"" job"');
    expect(csv).toContain('"\'=SUM(A1:A2)"');
    expect(csv).toContain('"First\nSecond"');
    expect(csv).toEndWith("\r\n");
  });

  test("write-only permission cannot export or retrieve a bundle", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.exports.project(writer)).toThrow("permission");
    expect(() => f.context.exports.bundle(writer, "job")).toThrow("permission");
    expect(() => f.context.exports.csv(writer)).toThrow("permission");
  });

  test("export and CSV routes expose distinct content types", async () => {
    using f = fixture();
    f.create();
    const json = await f.request("GET", "/exports", undefined, reader);
    expect(json.status).toBe(200);
    expect(json.headers.get("content-type")).toContain("application/json");
    const csv = await f.request("GET", "/exports/csv", undefined, reader);
    expect(csv.status).toBe(200);
    expect(csv.headers.get("content-type")).toContain("text/csv");
    expect(csv.headers.get("content-disposition")).toContain("jobs.csv");
    expect(await csv.text()).toContain('"job"');
  });
});

describe("export snapshots do not become live state", () => {
  test("previous exports stay immutable while new exports reflect evidence edits", () => {
    using f = fixture();
    f.create();
    f.attach();
    const before = f.context.exports.project(reader);
    const oldDigest = before.digest;
    f.context.evidence.patch(admin, "job", "evidence", { content: "Corrected", expectedRevision: 1 });
    const after = f.context.exports.project(reader);
    expect(before.digest).toBe(oldDigest);
    expect(before.jobs[0]?.evidence[0]?.content).toBe("Content evidence");
    expect(after.jobs[0]?.evidence[0]?.content).toBe("Corrected");
    expect(after.digest).not.toBe(before.digest);
    expect(f.context.exports.verify(before)).toBe(true);
    expect(f.context.exports.verify(after)).toBe(true);
  });

  test("an exported attempt is historical and does not introduce a running flag", () => {
    using f = fixture();
    f.create();
    f.context.builds.start(admin, "job", {
      id: "attempt", sessionId: "session", worker: "worker", expectedRevision: 1,
    });
    const document = f.context.exports.project(reader);
    const attempt = document.jobs[0]!.attempts[0]!;
    expect(attempt.finishedAt).toBeNull();
    expect(Object.hasOwn(attempt, "running")).toBe(false);
    f.context.sessions.endSession("session");
    expect(f.context.builds.list(reader, "job")[0]?.running).toBe(false);
    expect(attempt.finishedAt).toBeNull();
    expect(f.context.exports.verify(document)).toBe(true);
  });
});

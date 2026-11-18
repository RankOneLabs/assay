import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { checksum, byteLength } from "../../src/domain/checksum.ts";
import { values as kinds } from "../../evidence_kind/types.ts";

/** Kinds every version of the service keeps under the same spelling. */
const attachable = ["image", "testimony"] as const;


describe("evidence service", () => {
  test("attaches each kind to the same job without losing its vocabulary", () => {
    using f = fixture();
    f.create();
    for (const kind of attachable) {
      const item = f.attach(`item-${kind}`, "job", { kind });
      expect(item.kind).toBe(kind);
      expect(item.jobId).toBe("job");
      expect(item.revision).toBe(1);
      expect(item.checksum).toBe(checksum(item.content));
    }
    const items = f.context.evidence.list(reader, "job");
    expect(items).toHaveLength(attachable.length);
    for (const kind of attachable) {
      expect(f.context.evidence.list(reader, "job", kind)).toHaveLength(1);
    }
  });

  test("deduplicates content within a job even across different kinds", () => {
    using f = fixture();
    f.create();
    f.attach("first", "job", { content: "same bytes" });
    expect(() => f.attach("second", "job", {
      content: "same bytes", kind: "testimony",
    })).toThrow("already attached");
    expect(f.context.evidenceRepository.count("job")).toBe(1);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("the same content can be evidence for independent jobs", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    const first = f.attach("a", "first", { content: "shared source" });
    const second = f.attach("b", "second", { content: "shared source" });
    expect(first.checksum).toBe(second.checksum);
    expect(first.jobId).not.toBe(second.jobId);
    expect(f.context.evidence.list(admin, "first")).toHaveLength(1);
    expect(f.context.evidence.list(admin, "second")).toHaveLength(1);
  });

  test("evidence ids are globally unique", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.attach("same-id", "first");
    expect(() => f.attach("same-id", "second", { content: "different" })).toThrow("already exists");
    expect(f.context.evidenceRepository.count("first")).toBe(1);
    expect(f.context.evidenceRepository.count("second")).toBe(0);
  });

  test("patching title keeps content and digest stable", () => {
    using f = fixture();
    f.create();
    const item = f.attach();
    const changed = f.context.evidence.patch(admin, "job", item.id, {
      title: "Corrected title", expectedRevision: 1,
    });
    expect(changed.title).toBe("Corrected title");
    expect(changed.content).toBe(item.content);
    expect(changed.checksum).toBe(item.checksum);
    expect(changed.author).toBe(item.author);
    expect(changed.revision).toBe(2);
    expect(changed.createdAt).toBe(item.createdAt);
    expect(changed.updatedAt).toBeGreaterThan(item.updatedAt);
  });

  test("patching content recomputes its digest", () => {
    using f = fixture();
    f.create();
    const item = f.attach();
    const changed = f.context.evidence.patch(admin, "job", item.id, {
      content: "A corrected statement", expectedRevision: 1,
    });
    expect(changed.checksum).toBe(checksum("A corrected statement"));
    expect(changed.checksum).not.toBe(item.checksum);
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("evidence.patched");
    expect(JSON.parse(event.detail)).toMatchObject({ id: item.id, revision: 2 });
  });

  test("patches cannot duplicate another attachment's content", () => {
    using f = fixture();
    f.create();
    const original = f.attach("first");
    f.attach("second");
    expect(() => f.context.evidence.patch(admin, "job", "second", {
      content: original.content, expectedRevision: 1,
    })).toThrow("already attached");
    expect(f.context.evidenceRepository.require("second").revision).toBe(1);
    expect(f.context.eventRepository.count("job")).toBe(3);
  });

  test("a stale evidence patch does not change content or append history", () => {
    using f = fixture();
    f.create();
    const original = f.attach();
    expect(() => f.context.evidence.patch(admin, "job", original.id, {
      content: "not persisted", expectedRevision: 2,
    })).toThrow("revision changed");
    expect(f.context.evidenceRepository.require(original.id)).toEqual(original);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });

  test("removal verifies the revision and returns the deleted item", () => {
    using f = fixture();
    f.create();
    const original = f.attach();
    expect(() => f.context.evidence.remove(admin, "job", original.id, {
      expectedRevision: 3,
    })).toThrow("revision changed");
    const removed = f.context.evidence.remove(admin, "job", original.id, {
      expectedRevision: 1,
    });
    expect(removed).toEqual(original);
    expect(f.context.evidenceRepository.get(original.id)).toBeNull();
    expect(f.context.jobs.history(admin, "job").at(-1)?.action).toBe("evidence.removed");
  });

  test("count limit is enforced before adding evidence", () => {
    using f = fixture({ maxEvidence: 1 });
    f.create();
    f.attach("first");
    expect(() => f.attach("second")).toThrow("count limit");
    expect(f.context.evidenceRepository.count("job")).toBe(1);
    f.context.evidence.remove(admin, "job", "first", { expectedRevision: 1 });
    expect(f.attach("second").id).toBe("second");
    expect(f.context.evidenceRepository.count("job")).toBe(1);
  });

  test("byte limit counts UTF-8, not JavaScript characters", () => {
    using f = fixture({ maxEvidenceBytes: 5 });
    f.create();
    expect(byteLength("éé")).toBe(4);
    expect(byteLength("ééé")).toBe(6);
    expect(f.attach("first", "job", { content: "éé" }).content).toBe("éé");
    expect(() => f.attach("second", "job", { content: "ééé" })).toThrow("byte limit");
    expect(() => f.context.evidence.patch(admin, "job", "first", {
      content: "ééé", expectedRevision: 1,
    })).toThrow("byte limit");
    expect(f.context.evidenceRepository.require("first").content).toBe("éé");
  });

  test("readers cannot add, patch or remove evidence", () => {
    using f = fixture();
    f.create();
    f.attach();
    expect(() => f.context.evidence.attach(reader, "job", {
      id: "another", kind: "testimony", title: "No", content: "No", author: "reader",
    })).toThrow("permission");
    expect(() => f.context.evidence.patch(reader, "job", "evidence", {
      title: "No", expectedRevision: 1,
    })).toThrow("permission");
    expect(() => f.context.evidence.remove(reader, "job", "evidence", {
      expectedRevision: 1,
    })).toThrow("permission");
    expect(f.context.evidenceRepository.count("job")).toBe(1);
  });

  test("evidence lookup does not cross job boundaries", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.attach("item", "first");
    expect(() => f.context.evidence.get(admin, "second", "item")).toThrow("not found");
    expect(() => f.context.evidence.patch(admin, "second", "item", {
      title: "wrong job", expectedRevision: 1,
    })).toThrow("not found");
    expect(() => f.context.evidence.remove(admin, "second", "item", {
      expectedRevision: 1,
    })).toThrow("not found");
    expect(f.context.evidenceRepository.require("item").jobId).toBe("first");
  });

  test("both HTTP attachment peers accept existing kinds and reject unsupported_future", async () => {
    using f = fixture();
    f.create();
    for (const path of ["/jobs/job/evidence", "/jobs/job/evidence/peer"]) {
      const id = path.endsWith("peer") ? "peer" : "primary";
      const response = await f.request("POST", path, {
        id, kind: "testimony", title: "Proof", content: `Proof ${id}`, author: "writer",
      }, writer);
      expect(response.status).toBe(201);
      expect(await response.json()).toMatchObject({ kind: "testimony", jobId: "job" });
      await expectError(await f.request("POST", path, {
        id: `new-${id}`, kind: "unsupported_future", title: "Future", content: "Future", author: "writer",
      }, writer), 400);
    }
    expect(f.context.evidenceRepository.count("job")).toBe(2);
  });

  test("cross-project callers cannot read attachment content", async () => {
    using f = fixture();
    f.create();
    f.attach();
    await expectError(await f.request("GET", "/jobs/job/evidence/evidence/content", undefined, outsider), 403);
    const allowed = await f.request("GET", "/jobs/job/evidence/evidence/content", undefined, reader);
    expect(allowed.status).toBe(200);
    expect(allowed.headers.get("content-type")).toContain("text/markdown");
    expect(allowed.headers.get("x-content-type-options")).toBe("nosniff");
    expect(await allowed.text()).toBe("Content evidence");
  });
});

describe("evidence content workflows", () => {
  test("manifest exposes digest metadata without leaking evidence bodies", () => {
    using f = fixture();
    f.create();
    const item = f.attach("proof", "job", { content: "éé" });
    const manifest = f.context.evidence.manifest(reader, "job");
    expect(manifest.jobId).toBe("job");
    expect(manifest.count).toBe(1);
    expect(manifest.bytes).toBe(4);
    expect(manifest.items[0]).toEqual({
      id: "proof", kind: "testimony", title: item.title,
      checksum: item.checksum, revision: 1, bytes: 4, author: admin.id,
    });
    expect(Object.hasOwn(manifest.items[0]!, "content")).toBe(false);
  });

  test("verification detects content corruption in storage", () => {
    using f = fixture();
    f.create();
    f.attach();
    expect(f.context.evidence.verify(reader, "job").valid).toBe(true);
    f.context.db.query("UPDATE evidence SET content = ? WHERE id = ?").run("corrupted", "evidence");
    const result = f.context.evidence.verify(reader, "job");
    expect(result.valid).toBe(false);
    expect(result.checked).toBe(1);
    expect(result.checks[0]?.valid).toBe(false);
    expect(result.checks[0]?.actual).toBe(checksum("corrupted"));
    expect(result.checks[0]?.expected).not.toBe(result.checks[0]?.actual);
  });

  test("copy preserves source authorship and content while assigning a new identity", () => {
    using f = fixture();
    f.create("source");
    f.create("target");
    const original = f.attach("original", "source", { kind: "testimony", author: "witness" });
    const copied = f.context.evidence.copy(admin, "source", "original", "target", "copy");
    expect(copied.id).toBe("copy");
    expect(copied.jobId).toBe("target");
    expect(copied.kind).toBe("testimony");
    expect(copied.author).toBe("witness");
    expect(copied.checksum).toBe(original.checksum);
    expect(copied.content).toBe(original.content);
    expect(copied.revision).toBe(1);
    expect(f.context.evidenceRepository.require("original")).toEqual(original);
    const history = f.context.jobs.history(admin, "target");
    expect(history.at(-1)?.action).toBe("evidence.copied");
    expect(JSON.parse(history.at(-1)!.detail)).toMatchObject({ sourceJob: "source", sourceId: "original", targetId: "copy" });
  });

  test("copy cannot bypass content deduplication or target mutability", () => {
    using f = fixture();
    f.create("source");
    f.create("target");
    f.attach("original", "source");
    f.context.evidence.copy(admin, "source", "original", "target", "copy");
    expect(() => f.context.evidence.copy(admin, "source", "original", "target", "duplicate")).toThrow("already attached");
    f.context.jobs.archive(admin, "target", { expectedRevision: 1 });
    expect(() => f.context.evidence.copy(admin, "source", "original", "target", "blocked")).toThrow("read only");
    expect(f.context.evidenceRepository.get("duplicate")).toBeNull();
    expect(f.context.evidenceRepository.get("blocked")).toBeNull();
  });

  test("bulk attachment accepts mixed kinds in one atomic operation", () => {
    using f = fixture();
    f.create();
    const attached = f.context.evidence.bulkAttach(admin, "job", [
      { id: "a", kind: "testimony", title: "A", content: "A", author: "author" },
      { id: "b", kind: "image", title: "B", content: "B", author: "author" },
      { id: "c", kind: "testimony", title: "C", content: "C", author: "witness" },
    ], true);
    expect(attached.map(item => item.id)).toEqual(["a", "b", "c"]);
    expect(attached.map(item => item.kind)).toEqual(["testimony", "image", "testimony"]);
    expect(f.context.evidenceRepository.count("job")).toBe(3);
    expect(f.context.eventRepository.count("job")).toBe(4);
  });

  test("bulk attachment rolls back preceding attachments on a later content duplicate", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.evidence.bulkAttach(admin, "job", [
      { id: "a", kind: "testimony", title: "A", content: "same", author: "author" },
      { id: "b", kind: "image", title: "B", content: "same", author: "author" },
    ])).toThrow("already attached");
    expect(f.context.evidenceRepository.count("job")).toBe(0);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("bulk removal rolls back earlier deletions when a later revision is stale", () => {
    using f = fixture();
    f.create();
    f.attach("a");
    f.attach("b");
    expect(() => f.context.evidence.bulkRemove(admin, "job", [
      { id: "a", expectedRevision: 1 },
      { id: "b", expectedRevision: 2 },
    ])).toThrow("revision changed");
    expect(f.context.evidenceRepository.get("a")).not.toBeNull();
    expect(f.context.evidenceRepository.get("b")).not.toBeNull();
    expect(f.context.eventRepository.count("job")).toBe(3);
    const removed = f.context.evidence.bulkRemove(admin, "job", [
      { id: "a", expectedRevision: 1 },
      { id: "b", expectedRevision: 1 },
    ]);
    expect(removed).toHaveLength(2);
    expect(f.context.evidenceRepository.count("job")).toBe(0);
  });

  test("comparison uses content identity across independently named attachments", () => {
    using f = fixture();
    f.create("left");
    f.create("right");
    const shared = f.attach("left-shared", "left", { content: "shared" });
    f.attach("right-shared", "right", { content: "shared" });
    f.attach("left-only", "left");
    f.attach("right-only", "right");
    expect(f.context.evidence.compare(reader, "left", "right")).toEqual({
      leftJob: "left", rightJob: "right", shared: [shared.checksum],
      leftOnly: ["left-only"], rightOnly: ["right-only"],
    });
  });

  test("evidence search combines normalized text with kind and author filters", () => {
    using f = fixture();
    f.create();
    f.attach("matching", "job", { title: "Important Invoice", author: "sam" });
    f.attach("wrong-kind", "job", { title: "Invoice", kind: "image", author: "sam" });
    f.attach("wrong-author", "job", { title: "Invoice", author: "pat" });
    f.attach("wrong-query", "job", { title: "Unrelated", author: "sam" });
    const found = f.context.evidence.search(reader, "job", {
      query: "  INVOICE  ", kind: "testimony", author: "sam",
    });
    expect(found.map(item => item.id)).toEqual(["matching"]);
    expect(f.context.evidence.search(reader, "job", { query: "invoice", limit: 1 })).toHaveLength(1);
    expect(() => f.context.evidence.search(reader, "job", { query: "" })).toThrow();
  });

  test("content workflows are subject to read permissions and project isolation", () => {
    using f = fixture();
    f.create();
    f.attach();
    expect(() => f.context.evidence.manifest(writer, "job")).toThrow("permission");
    expect(() => f.context.evidence.verify(outsider, "job")).toThrow("another project");
    expect(() => f.context.evidence.search(writer, "job", { query: "Content" })).toThrow("permission");
    expect(() => f.context.evidence.compare(outsider, "job", "job")).toThrow("another project");
  });

  test("HTTP manifests, integrity checks, bulk attach and search use service workflows", async () => {
    using f = fixture();
    f.create();
    const attached = await f.request("POST", "/jobs/job/evidence/bulk", [
      { id: "a", kind: "testimony", title: "Invoice", content: "Data", author: "author" },
    ]);
    expect(attached.status).toBe(201);
    const manifest = await f.request("GET", "/jobs/job/evidence/manifest", undefined, reader);
    expect(await manifest.json()).toMatchObject({ count: 1, bytes: 4 });
    const verified = await f.request("GET", "/jobs/job/evidence/verify", undefined, reader);
    expect(await verified.json()).toMatchObject({ checked: 1, valid: true });
    const searched = await f.request("POST", "/jobs/job/evidence/search", { query: "invoice" }, reader);
    expect(await searched.json()).toMatchObject([{ id: "a" }]);
    const removed = await f.request("DELETE", "/jobs/job/evidence/bulk", [{ id: "a", expectedRevision: 1 }]);
    expect(removed.status).toBe(200);
    expect(f.context.evidenceRepository.count("job")).toBe(0);
  });
});

describe("saved evidence-kind source", () => {
  test("omitted kind consults the existing source and explicit kind takes precedence", () => {
    using f = fixture();
    f.create();
    f.context.evidence.setDefaultKind(admin, "image");
    const item = f.context.evidence.attach(admin, "job", {
      id: "implicit", title: "Implicit", content: "Image data", author: "author",
    });
    expect(item.kind).toBe("image");
    const explicit = f.context.evidence.attach(admin, "job", {
      id: "explicit", kind: "testimony", title: "Explicit", content: "Document data", author: "author",
    });
    expect(explicit.kind).toBe("testimony");
    expect(f.context.evidence.getDefaultKind(admin)).toBe("image");
    f.context.evidence.clearDefaultKind(admin);
    expect(f.context.evidence.getDefaultKind(admin)).toBeNull();
  });

  test("changing the saved source affects future attachments without changing old ones", () => {
    using f = fixture();
    f.create();
    f.context.evidence.setDefaultKind(admin, "testimony");
    f.context.evidence.attach(admin, "job", {
      id: "first", title: "First", content: "First", author: "author",
    });
    f.context.evidence.setDefaultKind(admin, "testimony");
    f.context.evidence.attach(admin, "job", {
      id: "second", title: "Second", content: "Second", author: "author",
    });
    expect(f.context.evidenceRepository.require("first").kind).toBe("testimony");
    expect(f.context.evidenceRepository.require("second").kind).toBe("testimony");
  });

  test("preferences isolate principals and cannot introduce a new vocabulary member", () => {
    using f = fixture();
    f.context.evidence.setDefaultKind(admin, "image");
    expect(f.context.evidence.getDefaultKind(writer)).toBeNull();
    expect(f.context.evidence.getDefaultKind(outsider)).toBeNull();
    expect(() => f.context.evidence.setDefaultKind(admin, "unsupported_future")).toThrow();
    expect(() => f.context.evidence.setDefaultKind(reader, "image")).toThrow("permission");
    expect(f.context.evidence.getDefaultKind(admin)).toBe("image");
  });

  test("HTTP kind defaults feed the real attachment route", async () => {
    using f = fixture();
    f.create();
    expect((await f.request("PUT", "/preferences/evidence-kind", { kind: "testimony" })).status).toBe(204);
    const selected = await f.request("GET", "/preferences/evidence-kind");
    expect(await selected.json()).toEqual({ kind: "testimony" });
    const attached = await f.request("POST", "/jobs/job/evidence", {
      id: "implicit", title: "Implicit", content: "Witness report", author: "witness",
    });
    expect(attached.status).toBe(201);
    expect(await attached.json()).toMatchObject({ kind: "testimony" });
    expect((await f.request("DELETE", "/preferences/evidence-kind")).status).toBe(204);
    const cleared = await f.request("GET", "/preferences/evidence-kind");
    expect(await cleared.json()).toEqual({ kind: null });
  });
});

describe("evidence HTTP representation", () => {
  test("each kind has a distinct media policy and a content digest ETag", async () => {
    using f = fixture();
    f.create();
    const expected = Object.fromEntries(attachable.map(kind =>
      [kind, ["text/plain", "image/png", "text/markdown"][kinds.indexOf(kind)] ?? "application/octet-stream"],
    ));
    for (const kind of attachable) {
      const item = f.attach(kind, "job", { kind });
      const content = await f.request("GET", `/jobs/job/evidence/${kind}/content`, undefined, reader);
      expect(content.status).toBe(200);
      expect(content.headers.get("content-type")).toContain(expected[kind]);
      expect(content.headers.get("etag")).toBe(`"${item.checksum}"`);
      expect(await content.text()).toBe(item.content);
      const metadata = await f.request("GET", `/jobs/job/evidence/${kind}`, undefined, reader);
      expect(metadata.headers.get("etag")).toBe('"1"');
      expect(await metadata.json()).toMatchObject({ kind, id: kind, revision: 1 });
    }
  });

  test("editing metadata changes its revision ETag without changing the content ETag", async () => {
    using f = fixture();
    f.create();
    const item = f.attach();
    const changed = await f.request("PATCH", "/jobs/job/evidence/evidence", {
      title: "Changed title", expectedRevision: 1,
    });
    expect(changed.status).toBe(200);
    const metadata = await f.request("GET", "/jobs/job/evidence/evidence", undefined, reader);
    const content = await f.request("GET", "/jobs/job/evidence/evidence/content", undefined, reader);
    expect(metadata.headers.get("etag")).toBe('"2"');
    expect(content.headers.get("etag")).toBe(`"${item.checksum}"`);
    expect(await content.text()).toBe(item.content);
  });

  test("kind filtering rejects unregistered names before touching persistence", async () => {
    using f = fixture();
    f.create();
    f.attach();
    const valid = await f.request("GET", `/jobs/job/evidence?kind=${"testimony"}`, undefined, reader);
    expect(await valid.json()).toMatchObject([{ id: "evidence" }]);
    await expectError(await f.request("GET", "/jobs/job/evidence?kind=unsupported_future", undefined, reader), 400);
    expect(f.context.evidenceRepository.count("job")).toBe(1);
    expect(f.context.eventRepository.count("job")).toBe(2);
  });
});

describe("default-kind validation boundaries", () => {
  test("a saved default does not make explicit null or unknown kinds valid", () => {
    using f = fixture();
    f.create();
    f.context.evidence.setDefaultKind(admin, "image");
    expect(() => f.context.evidence.attach(admin, "job", {
      id: "null-kind", title: "Null", content: "Null", author: "author", kind: null,
    })).toThrow();
    expect(() => f.context.evidence.attach(admin, "job", {
      id: "unknown-kind", title: "Unknown", content: "Unknown", author: "author", kind: "unsupported_future",
    })).toThrow();
    expect(f.context.evidenceRepository.count("job")).toBe(0);
    expect(f.context.evidence.getDefaultKind(admin)).toBe("image");
  });

  test("clearing the only default source makes omitted kind invalid again", () => {
    using f = fixture();
    f.create();
    f.context.evidence.setDefaultKind(admin, "testimony");
    f.context.evidence.clearDefaultKind(admin);
    expect(() => f.context.evidence.attach(admin, "job", {
      id: "missing-kind", title: "Missing", content: "Missing", author: "author",
    })).toThrow();
    expect(f.context.evidenceRepository.get("missing-kind")).toBeNull();
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("a default selected by one writer is not a fallback for another writer", () => {
    using f = fixture();
    f.create();
    f.context.evidence.setDefaultKind(admin, "testimony");
    expect(() => f.context.evidence.attach(writer, "job", {
      id: "missing", title: "Missing", content: "Missing", author: writer.id,
    })).toThrow();
    f.context.evidence.setDefaultKind(writer, "testimony");
    const attached = f.context.evidence.attach(writer, "job", {
      id: "selected", title: "Selected", content: "Selected", author: writer.id,
    });
    expect(attached.kind).toBe("testimony");
    expect(f.context.evidence.getDefaultKind(admin)).toBe("testimony");
  });
});

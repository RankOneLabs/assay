import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { parseMentions, maxReplyDepth, maxBodyLength, maxMentionsPerComment } from "../../src/domain/comments.ts";

describe("job comments", () => {
  test("replies nest under their parent and each addition is a job event", () => {
    using f = fixture();
    f.create();
    const root = f.context.comments.add(admin, "job", { id: "root", body: "Starting review" });
    const reply = f.context.comments.add(writer, "job", { id: "reply", body: "Looks fine", parentId: "root" });
    f.context.comments.add(admin, "job", { id: "second", body: "Another topic" });
    expect(root).toMatchObject({ depth: 0, parentId: null, author: "admin", revision: 1, deletedAt: null });
    expect(reply).toMatchObject({ depth: 1, parentId: "root", author: "writer" });
    const thread = f.context.comments.thread(reader, "job");
    expect(thread.total).toBe(3);
    expect(thread.comments.map(node => node.id)).toEqual(["root", "second"]);
    expect(thread.comments[0]!.replies.map(node => node.id)).toEqual(["reply"]);
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("comment.added");
    expect(JSON.parse(event.detail)).toEqual({ id: "second", parentId: null, mentions: [] });
  });

  test("reply nesting stops at the depth limit", () => {
    using f = fixture();
    f.create();
    let parentId: string | undefined;
    for (let depth = 0; depth <= maxReplyDepth; depth++) {
      f.context.comments.add(admin, "job", { id: `level-${depth}`, body: `level ${depth}`, parentId });
      parentId = `level-${depth}`;
    }
    expect(() => f.context.comments.add(admin, "job", { id: "too-deep", body: "deeper", parentId }))
      .toThrow("nesting limit");
    expect(f.context.comments.thread(admin, "job").total).toBe(maxReplyDepth + 1);
  });

  test("a reply must name a live comment of the same job", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.comments.add(admin, "first", { id: "elsewhere", body: "On the first job" });
    expect(() => f.context.comments.add(admin, "second", { id: "stray", body: "hi", parentId: "elsewhere" }))
      .toThrow("not found");
    f.context.comments.remove(admin, "first", "elsewhere", { expectedRevision: 1 });
    expect(() => f.context.comments.add(admin, "first", { id: "late", body: "hi", parentId: "elsewhere" }))
      .toThrow("deleted comment");
    expect(() => f.context.comments.add(admin, "first", { id: "elsewhere", body: "again" }))
      .toThrow("already exists");
  });

  test("bodies are trimmed and bounded", () => {
    using f = fixture();
    f.create();
    expect(f.context.comments.add(admin, "job", { id: "padded", body: "  spaced  " }).body).toBe("spaced");
    expect(() => f.context.comments.add(admin, "job", { id: "blank", body: "   " })).toThrow();
    expect(() => f.context.comments.add(admin, "job", { id: "long", body: "x".repeat(maxBodyLength + 1) })).toThrow();
    expect(() => f.context.comments.add(admin, "job", { id: "extra", body: "ok", pinned: true })).toThrow();
    expect(f.context.comments.thread(admin, "job").total).toBe(1);
  });

  test("reading needs read permission and writing needs case_write in the job's project", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(writer, "job", { id: "note", body: "Writer note" });
    expect(f.context.comments.get(reader, "job", "note").body).toBe("Writer note");
    expect(() => f.context.comments.add(reader, "job", { id: "nope", body: "Reader note" })).toThrow("permission");
    expect(() => f.context.comments.thread(writer, "job")).toThrow("permission");
    expect(() => f.context.comments.thread(outsider, "job")).toThrow("another project");
    expect(() => f.context.comments.add(outsider, "job", { id: "foreign", body: "hi" })).toThrow("another project");
  });

  test("archived and completed jobs refuse new, edited and deleted comments", () => {
    using f = fixture();
    f.create("archived");
    f.create("done");
    f.context.comments.add(admin, "archived", { id: "a", body: "before archive" });
    f.context.comments.add(admin, "done", { id: "d", body: "before completion" });
    f.context.jobs.archive(admin, "archived", { expectedRevision: 1 });
    f.context.jobs.transition(admin, "done", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "done", { stage: "complete", expectedRevision: 2, reason: "finish" });
    expect(() => f.context.comments.add(admin, "archived", { id: "a2", body: "late" })).toThrow("archived");
    expect(() => f.context.comments.edit(admin, "archived", "a", { body: "changed", expectedRevision: 1 }))
      .toThrow("archived");
    expect(() => f.context.comments.add(admin, "done", { id: "d2", body: "late" })).toThrow("read only");
    expect(() => f.context.comments.remove(admin, "done", "d", { expectedRevision: 1 })).toThrow("read only");
    expect(f.context.comments.thread(reader, "done").comments[0]!.body).toBe("before completion");
  });

  test("authors edit their own comments under a revision check and keep the history", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(writer, "job", { id: "note", body: "first draft" });
    expect(() => f.context.comments.edit(admin, "job", "note", { body: "hijack", expectedRevision: 1 }))
      .toThrow("only the author");
    expect(() => f.context.comments.edit(writer, "job", "note", { body: "first draft", expectedRevision: 1 }))
      .toThrow("does not change");
    const edited = f.context.comments.edit(writer, "job", "note", { body: "second draft @reader", expectedRevision: 1 });
    expect(edited).toMatchObject({ revision: 2, body: "second draft @reader", mentions: ["reader"] });
    expect(() => f.context.comments.edit(writer, "job", "note", { body: "stale", expectedRevision: 1 }))
      .toThrow("revision changed");
    const history = f.context.comments.history(reader, "job", "note");
    expect(history.versions.map(version => [version.revision, version.body])).toEqual([
      [1, "first draft"],
      [2, "second draft @reader"],
    ]);
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("comment.edited");
    expect(JSON.parse(event.detail)).toEqual({ id: "note", revision: 2, mentions: ["reader"] });
  });

  test("deletion keeps the thread shape but drops text, history and mentions", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(admin, "job", { id: "root", body: "ask @reader" });
    f.context.comments.edit(admin, "job", "root", { body: "ask @reader again", expectedRevision: 1 });
    f.context.comments.add(writer, "job", { id: "reply", body: "answer", parentId: "root" });
    expect(() => f.context.comments.remove(writer, "job", "root", { expectedRevision: 2 })).toThrow("administrator");
    const deleted = f.context.comments.remove(admin, "job", "root", { expectedRevision: 2 });
    expect(deleted).toMatchObject({ body: "", revision: 3, deletedBy: "admin", mentions: [] });
    expect(deleted.deletedAt).not.toBeNull();
    const thread = f.context.comments.thread(reader, "job");
    expect(thread).toMatchObject({ total: 2, deleted: 1 });
    expect(thread.comments[0]!.replies.map(node => node.id)).toEqual(["reply"]);
    expect(f.context.comments.history(reader, "job", "root")).toEqual({ id: "root", deleted: true, versions: [] });
    expect(f.context.comments.mentions(reader, {}).total).toBe(0);
    expect(() => f.context.comments.remove(admin, "job", "root", { expectedRevision: 3 })).toThrow("already deleted");
    expect(() => f.context.comments.edit(admin, "job", "root", { body: "revive", expectedRevision: 3 }))
      .toThrow("cannot be edited");
  });

  test("project administrators may delete another author's comment", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(writer, "job", { id: "note", body: "off topic" });
    f.context.comments.remove(admin, "job", "note", { expectedRevision: 1 });
    const event = f.context.jobs.history(admin, "job").at(-1)!;
    expect(event.action).toBe("comment.deleted");
    expect(JSON.parse(event.detail)).toEqual({ id: "note", author: "writer", moderated: true });
  });

  test("purging a job removes its comments and their mentions", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(admin, "job", { id: "note", body: "for @reader" });
    const archived = f.context.jobs.archive(admin, "job", { expectedRevision: 1 });
    f.context.maintenance.purge(admin, archived.archivedAt! + 1, 10);
    expect(f.context.db.query("SELECT COUNT(*) AS count FROM job_comments").get()).toEqual({ count: 0 });
    expect(f.context.comments.mentions(reader, {}).total).toBe(0);
  });
});

describe("mentions", () => {
  test("mentions start a word, follow key rules, skip the author and are unique", () => {
    expect(parseMentions("@pat and (@sam), mail pat@example.com, again @pat. @@lee", "admin")).toEqual(["pat", "sam"]);
    expect(parseMentions("note to self @admin", "admin")).toEqual([]);
    expect(() => parseMentions(`@${"a".repeat(81)}`, "admin")).toThrow("not a valid principal");
    const crowd = Array.from({ length: maxMentionsPerComment + 1 }, (_, index) => `@p${index}`).join(" ");
    expect(() => parseMentions(crowd, "admin")).toThrow("at most");
  });

  test("a mentioned principal sees unread mentions across the project and marks them read", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.comments.add(admin, "first", { id: "one", body: "@reader please check" });
    f.context.comments.add(writer, "second", { id: "two", body: "cc @reader @admin" });
    f.context.comments.add(admin, "second", { id: "three", body: "nobody named" });
    const inbox = f.context.comments.mentions(reader, {});
    expect(inbox.unread).toBe(2);
    expect(inbox.items.map(item => [item.commentId, item.jobId, item.readAt])).toEqual([
      ["two", "second", null],
      ["one", "first", null],
    ]);
    expect(f.context.comments.mentions(reader, { jobId: "first" }).items.map(item => item.commentId)).toEqual(["one"]);
    expect(f.context.comments.mentions(admin, {}).items.map(item => item.author)).toEqual(["writer"]);

    expect(f.context.comments.markMentions(reader, { commentIds: ["one", "three"] })).toEqual({ changed: 1, unread: 1 });
    expect(f.context.comments.mentions(reader, { unread: "true" }).items.map(item => item.commentId)).toEqual(["two"]);
    expect(f.context.comments.mentions(reader, { unread: "false" }).items.map(item => item.commentId)).toEqual(["one"]);
    expect(f.context.comments.markMentions(reader, { commentIds: ["one"], read: false })).toEqual({ changed: 1, unread: 2 });
    expect(f.context.comments.markAllRead(reader)).toEqual({ changed: 2, unread: 0 });
    expect(f.context.comments.mentions(reader, { limit: "1" })).toMatchObject({ total: 2, nextOffset: 1 });
  });

  test("edits keep read markers for retained mentions and add new ones unread", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(admin, "job", { id: "note", body: "@reader and @sam" });
    f.context.comments.markAllRead(reader);
    f.context.comments.edit(admin, "job", "note", { body: "@reader and @lee", expectedRevision: 1 });
    const stored = f.context.db.query<{ principal: string; read: number }, []>(
      "SELECT principal, read_at IS NOT NULL AS read FROM comment_mentions ORDER BY principal",
    ).all();
    expect(stored).toEqual([{ principal: "lee", read: 0 }, { principal: "reader", read: 1 }]);
  });

  test("the mention inbox needs read permission and stays inside the caller's project", () => {
    using f = fixture();
    f.create();
    f.context.comments.add(admin, "job", { id: "note", body: "@outsider look" });
    expect(() => f.context.comments.mentions(writer, {})).toThrow("permission");
    expect(f.context.comments.mentions(outsider, {}).total).toBe(0);
    expect(() => f.context.comments.markMentions(reader, { commentIds: ["note", "note"] })).toThrow();
  });
});

describe("comment routes", () => {
  test("create, read, edit, history and delete over HTTP", async () => {
    using f = fixture();
    f.create();
    const created = await f.request("POST", "/jobs/job/comments", { id: "note", body: "hello @reader" }, writer);
    expect(created.status).toBe(201);
    expect(created.headers.get("location")).toBe("/jobs/job/comments/note");
    const fetched = await f.request("GET", "/jobs/job/comments/note", undefined, reader);
    expect(fetched.headers.get("etag")).toBe('"1"');
    const edited = await f.request("PATCH", "/jobs/job/comments/note", { body: "hello again", expectedRevision: 1 }, writer);
    expect(await edited.json()).toMatchObject({ revision: 2, mentions: [] });
    const history = await f.request("GET", "/jobs/job/comments/note/history", undefined, reader);
    expect((await history.json() as { versions: unknown[] }).versions).toHaveLength(2);
    const removed = await f.request("DELETE", "/jobs/job/comments/note", { expectedRevision: 2 }, writer);
    expect(await removed.json()).toMatchObject({ body: "", revision: 3 });
    const thread = await f.request("GET", "/jobs/job/comments", undefined, reader);
    expect(await thread.json()).toMatchObject({ total: 1, deleted: 1 });
    await expectError(await f.request("POST", "/jobs/job/comments", { id: "x", body: "hi" }, reader), 403, "forbidden");
    await expectError(await f.request("POST", "/jobs/job/comments", { id: "x", body: "" }, writer), 400, "validation_failed");
    await expectError(await f.request("GET", "/jobs/job/comments/missing", undefined, reader), 404, "not_found");
  });

  test("mention inbox routes", async () => {
    using f = fixture();
    f.create();
    f.context.comments.add(admin, "job", { id: "note", body: "@reader ping" });
    const inbox = await f.request("GET", "/mentions?unread=true", undefined, reader);
    expect(await inbox.json()).toMatchObject({ unread: 1, total: 1, items: [{ commentId: "note", jobTitle: "Job job" }] });
    const marked = await f.request("POST", "/mentions/read", { commentIds: ["note"] }, reader);
    expect(await marked.json()).toEqual({ changed: 1, unread: 0 });
    const all = await f.request("POST", "/mentions/read-all", undefined, reader);
    expect(await all.json()).toEqual({ changed: 0, unread: 0 });
    await expectError(await f.request("GET", "/mentions?unread=maybe", undefined, reader), 400, "validation_failed");
  });
});

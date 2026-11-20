import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError, originalPermissions } from "./helpers.ts";
import { ServiceContext } from "../../src/context.ts";
import { createApp } from "../../src/app.ts";
import { readAccess } from "../../src/domain/access_levels.ts";
import { deliveryPolicy } from "../../src/domain/webhooks.ts";

/** A service whose clock only moves when a test moves it, for leases and retry schedules. */
function clocked() {
  const clock = { now: 1_000_000 };
  const context = new ServiceContext({}, () => clock.now);
  for (const permission of originalPermissions) context.grantRepository.grant(admin, permission, "bootstrap", 0);
  context.grantRepository.grant(reader, readAccess, "bootstrap", 0);
  context.grantRepository.grant(writer, "case_write", "bootstrap", 0);
  const app = createApp({}, context);
  return {
    clock,
    context,
    create(id = "job") {
      return context.jobs.create(admin, {
        id, title: `Job ${id}`, owner: "owner", project: admin.project,
      });
    },
    hook(id = "hook", url = `https://${id}.example.com/events`) {
      return context.webhooks.create(admin, { id, url });
    },
    request(method: string, path: string, body?: unknown) {
      return app.request(path, {
        method,
        headers: { "content-type": "application/json", "x-principal": admin.id, "x-project": admin.project },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    },
    [Symbol.dispose]() { context.close(); },
  };
}

function hmac(secret: string, body: string): string {
  return `sha256=${new Bun.CryptoHasher("sha256", secret).update(body).digest("hex")}`;
}

describe("subscriptions", () => {
  test("a reader subscribes to actions, prefixes, one job and one stage", () => {
    using f = fixture();
    f.create();
    const exact = f.context.subscriptions.create(reader, { id: "exact", pattern: "job.transitioned" });
    expect(exact).toMatchObject({ principal: reader.id, project: reader.project, jobId: null, stage: null });
    f.context.subscriptions.create(reader, { id: "prefix", pattern: "evidence." });
    const scoped = f.context.subscriptions.create(reader, {
      id: "scoped", pattern: "job.patched", jobId: "job", stage: "active",
    });
    expect(scoped).toMatchObject({ jobId: "job", stage: "active" });
    expect(f.context.subscriptions.list(reader).map(item => item.id)).toEqual(["exact", "prefix", "scoped"]);
    expect(f.context.subscriptions.list(admin)).toEqual([]);
  });

  test("patterns, stages and jobs are validated before anything is stored", () => {
    using f = fixture();
    f.context.jobs.create(outsider, { id: "foreign", title: "Foreign", owner: "owner", project: outsider.project });
    for (const pattern of ["Job.created", "job..created", ".job", "job created", ""]) {
      expect(() => f.context.subscriptions.create(reader, { id: "bad", pattern })).toThrow();
    }
    expect(() => f.context.subscriptions.create(reader, {
      id: "bad", pattern: "job.", stage: "unsupported_future",
    })).toThrow();
    expect(() => f.context.subscriptions.create(reader, { id: "bad", pattern: "job.", jobId: "missing" }))
      .toThrow("not found");
    expect(() => f.context.subscriptions.create(reader, { id: "bad", pattern: "job.", jobId: "foreign" }))
      .toThrow("another project");
    expect(f.context.subscriptions.list(reader)).toEqual([]);
  });

  test("identical filters and reused ids conflict", () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "first", pattern: "job." });
    expect(() => f.context.subscriptions.create(reader, { id: "second", pattern: "job." }))
      .toThrow("identical subscription");
    expect(() => f.context.subscriptions.create(admin, { id: "first", pattern: "evidence." }))
      .toThrow("already exists");
    f.context.subscriptions.create(admin, { id: "second", pattern: "job." });
  });

  test("only the owner can remove a subscription and read permission is required", () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "mine", pattern: "job." });
    expect(() => f.context.subscriptions.remove(admin, "mine")).toThrow("not found");
    expect(() => f.context.subscriptions.remove(outsider, "mine")).toThrow("not found");
    expect(() => f.context.subscriptions.create(writer, { id: "w", pattern: "job." })).toThrow("permission required");
    expect(() => f.context.subscriptions.list(writer)).toThrow("permission required");
    f.context.subscriptions.remove(reader, "mine");
    expect(f.context.subscriptions.list(reader)).toEqual([]);
  });

  test("subscription routes create, list and delete", async () => {
    using f = fixture();
    const created = await f.request("POST", "/subscriptions", { id: "web", pattern: "evidence." }, reader);
    expect(created.status).toBe(201);
    const listed = await f.request("GET", "/subscriptions", undefined, reader);
    expect((await listed.json() as { id: string }[]).map(item => item.id)).toEqual(["web"]);
    await expectError(await f.request("POST", "/subscriptions", { id: "w", pattern: "job." }, writer), 403, "forbidden");
    await expectError(await f.request("POST", "/subscriptions", { id: "w", pattern: "JOB" }, reader), 400);
    expect((await f.request("DELETE", "/subscriptions/web", undefined, reader)).status).toBe(204);
    await expectError(await f.request("DELETE", "/subscriptions/web", undefined, reader), 404, "not_found");
  });
});

describe("webhook endpoints", () => {
  test("creation shows the secret once and normalizes the url", () => {
    using f = fixture();
    const issued = f.context.webhooks.create(admin, { id: "hook", url: "https://Hooks.Example.com:443/in" });
    expect(issued.secret).toMatch(/^whsec_[0-9a-f]{48}$/);
    expect(issued.endpoint).toMatchObject({
      id: "hook", url: "https://hooks.example.com/in", active: true, revision: 1,
      secretHint: `...${issued.secret.slice(-4)}`,
    });
    const listed = f.context.webhooks.list(admin);
    expect(listed).toEqual([issued.endpoint]);
    expect(JSON.stringify(listed)).not.toContain(issued.secret);
  });

  test("urls must be https to a public host without credentials", () => {
    using f = fixture();
    for (const url of [
      "http://hooks.example.com/in",
      "ftp://hooks.example.com/in",
      "https://user:pass@hooks.example.com/in",
      "https://localhost/in",
      "https://api.localhost/in",
      "https://intranet/in",
      "https://build.internal/in",
      "https://printer.local/in",
      "https://127.0.0.1/in",
      "https://10.1.2.3/in",
      "https://172.20.0.1/in",
      "https://192.168.50.10/in",
      "https://169.254.169.254/latest",
      "https://[::1]/in",
      "not a url",
    ]) {
      expect(() => f.context.webhooks.create(admin, { id: "hook", url })).toThrow();
    }
    expect(f.context.webhooks.list(admin)).toEqual([]);
    expect(f.context.webhooks.create(admin, { id: "hook", url: "https://172.32.0.1/in" }).endpoint.active).toBe(true);
  });

  test("a url is registered once per project and edits check the revision", () => {
    using f = fixture();
    f.context.webhooks.create(admin, { id: "first", url: "https://hooks.example.com/a" });
    f.context.webhooks.create(admin, { id: "second", url: "https://hooks.example.com/b" });
    expect(() => f.context.webhooks.create(admin, { id: "third", url: "https://hooks.example.com/a" }))
      .toThrow("already uses this url");
    expect(() => f.context.webhooks.update(admin, "second", { url: "https://hooks.example.com/a", expectedRevision: 1 }))
      .toThrow("already uses this url");
    const paused = f.context.webhooks.update(admin, "second", { active: false, expectedRevision: 1 });
    expect(paused).toMatchObject({ active: false, revision: 2, url: "https://hooks.example.com/b" });
    expect(() => f.context.webhooks.update(admin, "second", { active: true, expectedRevision: 1 }))
      .toThrow("revision changed");
    expect(() => f.context.webhooks.update(admin, "second", { expectedRevision: 2 })).toThrow();
  });

  test("rotation issues a new secret and bumps the revision", () => {
    using f = fixture();
    const issued = f.context.webhooks.create(admin, { id: "hook", url: "https://hooks.example.com/in" });
    const rotated = f.context.webhooks.rotate(admin, "hook", { expectedRevision: 1 });
    expect(rotated.secret).not.toBe(issued.secret);
    expect(rotated.endpoint).toMatchObject({ revision: 2, secretHint: `...${rotated.secret.slice(-4)}` });
    expect(() => f.context.webhooks.rotate(admin, "hook", { expectedRevision: 1 })).toThrow("revision changed");
  });

  test("endpoints are administrator-only and invisible across projects", () => {
    using f = fixture();
    f.context.webhooks.create(admin, { id: "hook", url: "https://hooks.example.com/in" });
    expect(() => f.context.webhooks.list(reader)).toThrow("permission required");
    expect(() => f.context.webhooks.create(writer, { id: "w", url: "https://w.example.com/" }))
      .toThrow("permission required");
    expect(() => f.context.webhooks.get(outsider, "hook")).toThrow("not found");
    expect(() => f.context.webhooks.remove(outsider, "hook", { expectedRevision: 1 })).toThrow("not found");
    expect(f.context.webhooks.get(admin, "hook").id).toBe("hook");
  });

  test("webhook routes manage an endpoint end to end", async () => {
    using f = fixture();
    const created = await f.request("POST", "/webhooks", { id: "hook", url: "https://hooks.example.com/in" });
    expect(created.status).toBe(201);
    expect(created.headers.get("location")).toBe("/webhooks/hook");
    const { secret } = await created.json() as { secret: string };
    const fetched = await f.request("GET", "/webhooks/hook");
    expect(fetched.headers.get("etag")).toBe('"1"');
    expect(await fetched.text()).not.toContain(secret);
    expect((await f.request("PATCH", "/webhooks/hook", { active: false, expectedRevision: 1 })).status).toBe(200);
    const rotated = await f.request("POST", "/webhooks/hook/rotate", { expectedRevision: 2 });
    expect((await rotated.json() as { secret: string }).secret).not.toBe(secret);
    await expectError(await f.request("POST", "/webhooks", { id: "bad", url: "http://hooks.example.com/" }), 400);
    await expectError(await f.request("GET", "/webhooks", undefined, reader), 403, "forbidden");
    await expectError(await f.request("DELETE", "/webhooks/hook", { expectedRevision: 2 }), 409, "conflict");
    expect((await f.request("DELETE", "/webhooks/hook", { expectedRevision: 3 })).status).toBe(204);
    expect((await (await f.request("GET", "/webhooks")).json() as unknown[])).toEqual([]);
  });
});

describe("outbox collection", () => {
  test("collect fans each event out once and advances the cursor", () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "jobs", pattern: "job." });
    f.create();
    f.context.jobs.patch(admin, "job", { title: "Renamed", expectedRevision: 1 });
    const first = f.context.outbox.collect(admin, {});
    const events = f.context.jobs.history(admin, "job");
    expect(first).toEqual({ events: 2, notifications: 2, deliveries: 0, cursor: events.at(-1)!.sequence, more: false });
    expect(f.context.outbox.collect(admin, {})).toMatchObject({ events: 0, notifications: 0, cursor: first.cursor });
    f.attach();
    expect(f.context.outbox.collect(admin, {})).toMatchObject({ events: 1, notifications: 0 });
    const inbox = f.context.notifications.inbox(reader, {});
    expect(inbox.map(item => item.action)).toEqual(["job.patched", "job.created"]);
    expect(inbox[0]!.payload).toMatchObject({
      action: "job.patched", jobId: "job", jobTitle: "Renamed", actor: admin.id, project: admin.project,
      detail: { revision: 2 },
    });
  });

  test("a batch limit leaves the rest for the next pass", () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "all", pattern: "job." });
    f.create("first");
    f.create("second");
    f.create("third");
    expect(f.context.outbox.collect(admin, { limit: 2 })).toMatchObject({ events: 2, more: true });
    expect(f.context.outbox.collect(admin, { limit: 2 })).toMatchObject({ events: 1, more: false });
    expect(f.context.notifications.inbox(reader, {})).toHaveLength(3);
    expect(() => f.context.outbox.collect(admin, { limit: 501 })).toThrow();
  });

  test("job and stage filters use the job as it stands at collection", () => {
    using f = fixture();
    f.create("watched");
    f.create("other");
    f.context.subscriptions.create(reader, { id: "one-job", pattern: "job.", jobId: "watched" });
    f.context.subscriptions.create(outsider, { id: "foreign", pattern: "job." });
    f.context.grantRepository.grant({ id: "lead", project: admin.project }, readAccess, "bootstrap", 0);
    const lead = { id: "lead", project: admin.project };
    f.context.subscriptions.create(lead, { id: "active-only", pattern: "job.", stage: "active" });
    f.context.jobs.transition(admin, "other", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.outbox.collect(admin, {});
    expect(f.context.notifications.inbox(reader, {}).map(item => item.jobId)).toEqual(["watched"]);
    expect(f.context.notifications.inbox(lead, {}).map(item => item.action))
      .toEqual(["job.transitioned", "job.created"]);
    expect(f.context.notifications.inbox(lead, {})[0]!.payload).toMatchObject({ stage: "active" });
    expect(f.context.notifications.inbox(outsider, {})).toEqual([]);
  });

  test("actors, readers who lost access and overlapping subscriptions", () => {
    using f = fixture();
    f.context.subscriptions.create(admin, { id: "own", pattern: "job." });
    f.context.subscriptions.create(reader, { id: "broad", pattern: "job." });
    f.context.subscriptions.create(reader, { id: "narrow", pattern: "job.created" });
    f.create("first");
    f.context.outbox.collect(admin, {});
    expect(f.context.notifications.inbox(admin, {})).toEqual([]);
    expect(f.context.notifications.inbox(reader, {}).map(item => item.subscriptionId)).toEqual(["broad"]);
    f.context.grantRepository.revoke(reader, readAccess);
    f.create("second");
    expect(f.context.outbox.collect(admin, {})).toMatchObject({ events: 1, notifications: 0 });
    f.context.grantRepository.grant(reader, readAccess, "bootstrap", 0);
    expect(f.context.subscriptions.list(reader)).toHaveLength(2);
  });

  test("collection needs administration and stays inside the project", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.outbox.collect(reader, {})).toThrow("permission required");
    expect(() => f.context.outbox.collect(writer, {})).toThrow("permission required");
    expect(f.context.outbox.collect(outsider, {})).toMatchObject({ events: 0, cursor: 0 });
    expect(f.context.outbox.collect(admin, {})).toMatchObject({ events: 1 });
  });
});

describe("webhook delivery", () => {
  test("active endpoints get one signed delivery per event", () => {
    using f = clocked();
    const { secret } = f.hook();
    f.context.webhooks.create(admin, { id: "paused", url: "https://paused.example.com/", active: false });
    f.create();
    expect(f.context.outbox.collect(admin, {})).toMatchObject({ events: 1, deliveries: 1 });
    const [claimed] = f.context.outbox.claim(admin, { worker: "sender" });
    expect(claimed).toMatchObject({ attempt: 1, leaseExpiresAt: f.clock.now + 30_000 });
    expect(claimed!.request).toMatchObject({ method: "POST", url: "https://hook.example.com/events" });
    expect(claimed!.request.headers).toMatchObject({
      "webhook-event": "job.created",
      "webhook-timestamp": String(f.clock.now),
      "webhook-signature": hmac(secret, claimed!.request.body),
    });
    expect(JSON.parse(claimed!.request.body)).toMatchObject({ action: "job.created", jobId: "job" });
    expect(f.context.outbox.claim(admin, { worker: "sender" })).toEqual([]);
  });

  test("a lapsed lease makes the delivery claimable and voids the old token", () => {
    using f = clocked();
    f.hook();
    f.create();
    f.context.outbox.collect(admin, {});
    const [first] = f.context.outbox.claim(admin, { worker: "a", leaseMs: 5000 });
    f.clock.now += 4999;
    expect(f.context.outbox.claim(admin, { worker: "b" })).toEqual([]);
    f.clock.now += 1;
    expect(() => f.context.outbox.report(admin, first!.id, { leaseToken: first!.leaseToken, status: 200 }))
      .toThrow("not leased");
    const [second] = f.context.outbox.claim(admin, { worker: "b" });
    expect(second!.id).toBe(first!.id);
    expect(() => f.context.outbox.report(admin, first!.id, { leaseToken: first!.leaseToken, status: 200 }))
      .toThrow("not leased");
    const delivered = f.context.outbox.report(admin, second!.id, { leaseToken: second!.leaseToken, status: 204 });
    expect(delivered).toMatchObject({ status: "delivered", attempts: 1, lastStatus: 204, leaseExpiresAt: null });
    f.clock.now += 60_000;
    expect(f.context.outbox.claim(admin, { worker: "b" })).toEqual([]);
  });

  test("failures back off exponentially and then dead-letter", () => {
    using f = clocked();
    f.hook();
    f.create();
    f.context.outbox.collect(admin, {});
    const delays: number[] = [];
    for (let attempt = 1; attempt <= deliveryPolicy.maxAttempts; attempt++) {
      const [claimed] = f.context.outbox.claim(admin, { worker: "sender" });
      expect(claimed!.attempt).toBe(attempt);
      const result = f.context.outbox.report(admin, claimed!.id, { leaseToken: claimed!.leaseToken, status: 503 });
      if (result.status === "pending") {
        delays.push(result.nextAttemptAt - f.clock.now);
        f.clock.now = result.nextAttemptAt - 1;
        expect(f.context.outbox.claim(admin, { worker: "sender" })).toEqual([]);
        f.clock.now += 1;
      } else {
        expect(result).toMatchObject({ status: "dead", attempts: deliveryPolicy.maxAttempts, lastStatus: 503 });
      }
    }
    expect(delays).toEqual([60_000, 120_000, 240_000, 480_000, 960_000]);
    expect(f.context.outbox.deadLetters(admin, {}).map(item => item.status)).toEqual(["dead"]);
  });

  test("410 dead-letters at once and redelivery restarts the attempt budget", () => {
    using f = clocked();
    f.hook();
    f.create();
    f.context.outbox.collect(admin, {});
    const [claimed] = f.context.outbox.claim(admin, { worker: "sender" });
    expect(f.context.outbox.report(admin, claimed!.id, { leaseToken: claimed!.leaseToken, status: 410 }))
      .toMatchObject({ status: "dead", attempts: 1 });
    f.context.webhooks.update(admin, "hook", { active: false, expectedRevision: 1 });
    expect(() => f.context.outbox.redeliver(admin, claimed!.id)).toThrow("inactive");
    f.context.webhooks.update(admin, "hook", { active: true, expectedRevision: 2 });
    expect(f.context.outbox.redeliver(admin, claimed!.id)).toMatchObject({
      status: "pending", attempts: 0, nextAttemptAt: f.clock.now, lastStatus: 410,
    });
    expect(() => f.context.outbox.redeliver(admin, claimed!.id)).toThrow("only dead deliveries");
    expect(f.context.outbox.deadLetters(admin, {})).toEqual([]);
    expect(f.context.outbox.claim(admin, { worker: "sender" })[0]!.attempt).toBe(1);
  });

  test("rotation re-signs and deletion drops pending deliveries", () => {
    using f = clocked();
    f.hook();
    f.create();
    f.context.outbox.collect(admin, {});
    const { secret } = f.context.webhooks.rotate(admin, "hook", { expectedRevision: 1 });
    const [claimed] = f.context.outbox.claim(admin, { worker: "sender", leaseMs: 1000 });
    expect(claimed!.request.headers["webhook-signature"]).toBe(hmac(secret, claimed!.request.body));
    f.context.webhooks.remove(admin, "hook", { expectedRevision: 2 });
    f.clock.now += 1000;
    expect(f.context.outbox.claim(admin, { worker: "sender" })).toEqual([]);
    expect(() => f.context.outbox.redeliver(admin, claimed!.id)).toThrow("not found");
  });

  test("workers need administration, valid reports, and their own project", () => {
    using f = clocked();
    f.hook();
    f.create();
    f.context.outbox.collect(admin, {});
    expect(() => f.context.outbox.claim(reader, { worker: "sender" })).toThrow("permission required");
    const [claimed] = f.context.outbox.claim(admin, { worker: "sender" });
    const report = { leaseToken: claimed!.leaseToken, status: 200 };
    expect(() => f.context.outbox.report(writer, claimed!.id, report)).toThrow("permission required");
    f.context.grantRepository.grant(outsider, "case_admin", "bootstrap", 0);
    expect(() => f.context.outbox.report(outsider, claimed!.id, report)).toThrow("not found");
    expect(() => f.context.outbox.report(admin, claimed!.id, { ...report, status: 600 })).toThrow();
    expect(() => f.context.outbox.report(admin, claimed!.id, { ...report, leaseToken: "token" })).toThrow();
    expect(() => f.context.outbox.claim(admin, { worker: "sender", leaseMs: 10 })).toThrow();
  });

  test("outbox routes collect, claim, report and redeliver", async () => {
    using f = clocked();
    f.hook();
    f.create();
    expect(await (await f.request("POST", "/outbox/collect", {})).json()).toMatchObject({ events: 1, deliveries: 1 });
    const claimed = await (await f.request("POST", "/outbox/claim", { worker: "sender" })).json() as
      { id: number; leaseToken: string }[];
    expect(claimed).toHaveLength(1);
    const id = claimed[0]!.id;
    const reported = await f.request("POST", `/outbox/deliveries/${id}/report`, {
      leaseToken: claimed[0]!.leaseToken, status: 410,
    });
    expect(await reported.json()).toMatchObject({ status: "dead" });
    const dead = await (await f.request("GET", "/outbox/dead?limit=5")).json() as { id: number }[];
    expect(dead.map(item => item.id)).toEqual([id]);
    expect(await (await f.request("POST", `/outbox/deliveries/${id}/redeliver`)).json())
      .toMatchObject({ status: "pending" });
    await expectError(await f.request("POST", `/outbox/deliveries/${id}/redeliver`), 409, "conflict");
    await expectError(await f.request("POST", "/outbox/deliveries/zero/redeliver"), 400);
    await expectError(await f.request("POST", "/outbox/deliveries/999/redeliver"), 404, "not_found");
  });
});

describe("principal notifications", () => {
  test("the inbox lists unread newest first and marks only one's own as read", () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "all", pattern: "job." });
    f.context.subscriptions.create(admin, { id: "admin-evidence", pattern: "evidence." });
    f.create("first");
    f.create("second");
    f.context.jobs.patch(admin, "first", { priority: 5, expectedRevision: 1 });
    f.context.outbox.collect(admin, {});
    const inbox = f.context.notifications.inbox(reader, {});
    expect(inbox.map(item => [item.action, item.jobId])).toEqual([
      ["job.patched", "first"], ["job.created", "second"], ["job.created", "first"],
    ]);
    expect(f.context.notifications.inbox(reader, { limit: "1" })).toHaveLength(1);
    expect(f.context.notifications.markRead(outsider, { ids: [inbox[0]!.id] })).toEqual({ marked: 0 });
    expect(f.context.notifications.markRead(reader, { ids: [inbox[0]!.id, inbox[1]!.id] })).toEqual({ marked: 2 });
    expect(f.context.notifications.markRead(reader, { ids: [inbox[0]!.id] })).toEqual({ marked: 0 });
    expect(f.context.notifications.inbox(reader, {}).map(item => item.id)).toEqual([inbox[2]!.id]);
    const all = f.context.notifications.inbox(reader, { unread: "false" });
    expect(all.map(item => item.readAt === null)).toEqual([false, false, true]);
  });

  test("counts are grouped by action", () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "everything", pattern: "job." });
    f.context.subscriptions.create(reader, { id: "evidence", pattern: "evidence." });
    f.create();
    f.attach("one");
    f.attach("two");
    f.context.outbox.collect(admin, {});
    const [evidence] = f.context.notifications.inbox(reader, {});
    f.context.notifications.markRead(reader, { ids: [evidence!.id] });
    expect(f.context.notifications.counts(reader)).toEqual({
      unread: 2,
      actions: [
        { action: "evidence.attached", unread: 1, total: 2 },
        { action: "job.created", unread: 1, total: 1 },
      ],
    });
    expect(f.context.notifications.counts(admin)).toEqual({ unread: 0, actions: [] });
  });

  test("notification routes need read permission and validate input", async () => {
    using f = fixture();
    f.context.subscriptions.create(reader, { id: "all", pattern: "job." });
    f.create();
    f.context.outbox.collect(admin, {});
    const inbox = await (await f.request("GET", "/notifications", undefined, reader)).json() as { id: number }[];
    expect(inbox).toHaveLength(1);
    const marked = await f.request("POST", "/notifications/read", { ids: [inbox[0]!.id] }, reader);
    expect(await marked.json()).toEqual({ marked: 1 });
    expect(await (await f.request("GET", "/notifications", undefined, reader)).json()).toEqual([]);
    expect(await (await f.request("GET", "/notifications?unread=false", undefined, reader)).json()).toHaveLength(1);
    expect(await (await f.request("GET", "/notifications/counts", undefined, reader)).json())
      .toEqual({ unread: 0, actions: [{ action: "job.created", unread: 0, total: 1 }] });
    await expectError(await f.request("GET", "/notifications", undefined, writer), 403, "forbidden");
    await expectError(await f.request("GET", "/notifications?unread=maybe", undefined, reader), 400);
    await expectError(await f.request("POST", "/notifications/read", { ids: [] }, reader), 400);
  });
});

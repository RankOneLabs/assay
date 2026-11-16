import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider } from "./helpers.ts";

const request = { id: "attempt", sessionId: "session", worker: "worker" };

describe("ready queue dispatch", () => {
  test("an empty queue returns no attempt and consumes no live capacity", () => {
    using f = fixture();
    expect(f.context.dispatch.next(admin, request)).toBeNull();
    expect(f.context.dispatch.capacity(reader)).toEqual({ maximum: 10, used: 0, available: 10, workers: [] });
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
  });

  test("dispatch selects highest priority eligible queued work", () => {
    using f = fixture();
    f.create("low", { priority: 1 });
    f.create("high", { priority: 99 });
    const result = f.context.dispatch.next(admin, request)!;
    expect(result.job.id).toBe("high");
    expect(result.job.stage).toBe("active");
    expect(result.attempt.jobId).toBe("high");
    expect(result.attempt.sessionId).toBe("session");
    expect(f.context.jobRepository.require("low").stage).toBe("queued");
    expect(f.context.sessions.isBuildRunning("session")).toBe(true);
  });

  test("dispatch skips blocked work even if it has higher priority", () => {
    using f = fixture();
    f.create("dependency", { priority: 1 });
    f.create("blocked", { priority: 100 });
    f.context.planning.add(admin, "blocked", "dependency");
    const result = f.context.dispatch.next(admin, request)!;
    expect(result.job.id).toBe("dependency");
    expect(f.context.jobRepository.require("blocked").stage).toBe("queued");
  });

  test("owner and minimum priority filters combine before selection", () => {
    using f = fixture();
    f.create("wrong-owner", { owner: "other-owner", priority: 99 });
    f.create("too-low", { owner: "selected", priority: 1 });
    f.create("match", { owner: "selected", priority: 9 });
    const result = f.context.dispatch.next(admin, {
      ...request, owner: "selected", minimumPriority: 5,
    })!;
    expect(result.job.id).toBe("match");
    expect(f.context.jobRepository.require("wrong-owner").stage).toBe("queued");
    expect(f.context.jobRepository.require("too-low").stage).toBe("queued");
  });

  test("configured concurrent build capacity is enforced from the session owner", () => {
    using f = fixture({ maxConcurrentBuilds: 1 });
    f.create("first");
    f.create("second");
    f.context.dispatch.next(admin, request);
    expect(f.context.dispatch.capacity(reader)).toEqual({ maximum: 1, used: 1, available: 0, workers: ["worker"] });
    expect(() => f.context.dispatch.next(admin, {
      id: "another", sessionId: "another-session", worker: "another-worker",
    })).toThrow("concurrent build limit");
    expect(f.context.jobRepository.require("second").stage).toBe("queued");
  });

  test("ending live session ownership frees capacity without guessing from job stage", () => {
    using f = fixture({ maxConcurrentBuilds: 1 });
    f.create("first");
    f.create("second");
    f.context.dispatch.next(admin, request);
    f.context.sessions.endSession("session");
    expect(f.context.jobRepository.require("first").stage).toBe("active");
    expect(f.context.dispatch.capacity(reader).available).toBe(1);
    const next = f.context.dispatch.next(admin, {
      id: "another", sessionId: "another-session", worker: "worker",
    })!;
    expect(next.job.id).toBe("second");
  });

  test("a worker cannot receive two simultaneous builds in the same project", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.dispatch.next(admin, request);
    expect(() => f.context.dispatch.next(admin, {
      id: "another", sessionId: "another-session", worker: "worker",
    })).toThrow("worker already has");
    expect(f.context.dispatch.running(reader)).toHaveLength(1);
  });

  test("project dispatch does not consume jobs from another project", () => {
    using f = fixture();
    f.create();
    expect(f.context.dispatch.next(outsider, request)).toBeNull();
    expect(f.context.dispatch.running(outsider)).toEqual([]);
    expect(f.context.jobRepository.require("job").stage).toBe("queued");
  });

  test("archived and completed jobs are never selected", () => {
    using f = fixture();
    f.create("archived");
    f.create("completed");
    f.context.jobs.archive(admin, "archived", { expectedRevision: 1 });
    f.context.jobs.transition(admin, "completed", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "completed", { stage: "complete", expectedRevision: 2, reason: "done" });
    expect(f.context.dispatch.next(admin, request)).toBeNull();
    expect(f.context.sessions.isBuildRunning("session")).toBe(false);
  });

  test("dispatch requires both read and write while capacity only requires read", () => {
    using f = fixture();
    f.create();
    expect(() => f.context.dispatch.next(reader, request)).toThrow("permission");
    expect(() => f.context.dispatch.next(writer, request)).toThrow("permission");
    expect(() => f.context.dispatch.capacity(writer)).toThrow("permission");
    expect(f.context.dispatch.capacity(reader).used).toBe(0);
  });

  test("HTTP dispatch reports an empty queue with no body", async () => {
    using f = fixture();
    const empty = await f.request("POST", "/dispatch", request);
    expect(empty.status).toBe(204);
    expect(await empty.text()).toBe("");
    f.create();
    const dispatched = await f.request("POST", "/dispatch", request);
    expect(dispatched.status).toBe(201);
    expect(await dispatched.json()).toMatchObject({ job: { id: "job", stage: "active" } });
    const capacity = await f.request("GET", "/dispatch/capacity", undefined, reader);
    expect(await capacity.json()).toMatchObject({ used: 1, available: 9 });
    const running = await f.request("GET", "/dispatch/running", undefined, reader);
    expect(await running.json()).toMatchObject([{ attempt: { sessionId: "session" } }]);
  });
});

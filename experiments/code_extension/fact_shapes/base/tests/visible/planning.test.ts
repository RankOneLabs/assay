import { describe, expect, test } from "bun:test";
import { adjacency, ancestors, descendants, plan, impact } from "../../src/domain/graph.ts";
import { fixture, admin, reader, writer, outsider } from "./helpers.ts";

describe("dependency graph algorithms", () => {
  test("empty plans have no artificial root", () => {
    expect(plan([], [])).toEqual({ order: [], layers: [], roots: [], leaves: [] });
  });

  test("independent jobs share a sorted execution layer", () => {
    expect(plan(["c", "a", "b"], [])).toEqual({
      order: ["a", "b", "c"], layers: [["a", "b", "c"]],
      roots: ["a", "b", "c"], leaves: ["a", "b", "c"],
    });
  });

  test("diamond dependencies produce deterministic layers", () => {
    const result = plan(["end", "right", "left", "start"], [
      { jobId: "left", requiresId: "start" },
      { jobId: "right", requiresId: "start" },
      { jobId: "end", requiresId: "left" },
      { jobId: "end", requiresId: "right" },
    ]);
    expect(result.order).toEqual(["start", "left", "right", "end"]);
    expect(result.layers).toEqual([["start"], ["left", "right"], ["end"]]);
    expect(result.roots).toEqual(["start"]);
    expect(result.leaves).toEqual(["end"]);
  });

  test("graph traversal deduplicates common ancestors and descendants", () => {
    const edges = [
      { jobId: "left", requiresId: "root" },
      { jobId: "right", requiresId: "root" },
      { jobId: "end", requiresId: "left" },
      { jobId: "end", requiresId: "right" },
    ];
    const graph = adjacency(["root", "left", "right", "end"], edges);
    expect(ancestors("end", graph)).toEqual(["left", "right", "root"]);
    expect(descendants("root", graph)).toEqual(["end", "left", "right"]);
    expect(impact("left", [...graph.keys()], edges)).toEqual({
      id: "left", prerequisites: ["root"], dependents: ["end"], direct: ["root"],
    });
  });

  test("cycles, self references and unknown graph ids are rejected", () => {
    expect(() => plan(["a", "b"], [
      { jobId: "a", requiresId: "b" }, { jobId: "b", requiresId: "a" },
    ])).toThrow("cycle");
    expect(() => plan(["a"], [{ jobId: "a", requiresId: "a" }])).toThrow("cycle");
    expect(() => plan(["a"], [{ jobId: "a", requiresId: "missing" }])).toThrow("outside");
    expect(() => plan(["a", "a"], [])).toThrow("duplicate");
    expect(() => ancestors("missing", new Map())).toThrow("unknown");
  });

  test("a long chain does not depend on JavaScript recursion depth", () => {
    const ids = Array.from({ length: 15000 }, (_, index) => `job-${index}`);
    const edges = ids.slice(1).map((id, index) => ({ jobId: id, requiresId: ids[index]! }));
    const result = plan(ids, edges);
    expect(result.order).toEqual(ids);
    expect(result.layers).toHaveLength(ids.length);
    expect(result.roots).toEqual([ids[0]!]);
    expect(result.leaves).toEqual([ids.at(-1)!]);
  });
});

describe("persisted project planning", () => {
  test("adding a dependency changes readiness and records provenance", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    expect(f.context.planning.add(admin, "second", "first")).toBe(true);
    expect(f.context.planning.ready(reader).map(job => job.id)).toEqual(["first"]);
    expect(f.context.planning.blockers(reader, "second").map(job => job.id)).toEqual(["first"]);
    const event = f.context.jobs.history(admin, "second").at(-1)!;
    expect(event.action).toBe("dependency.added");
    expect(JSON.parse(event.detail)).toEqual({ requiresId: "first" });
  });

  test("duplicate dependency requests do not append duplicate events", () => {
    using f = fixture();
    f.create("a");
    f.create("b");
    expect(f.context.planning.add(admin, "b", "a")).toBe(true);
    expect(f.context.planning.add(admin, "b", "a")).toBe(false);
    expect(f.context.eventRepository.count("b")).toBe(2);
    expect(f.context.planning.projectPlan(reader).layers).toEqual([["a"], ["b"]]);
  });

  test("a cycle attempt rolls back the inserted edge and its event", () => {
    using f = fixture();
    f.create("a");
    f.create("b");
    f.create("c");
    f.context.planning.add(admin, "b", "a");
    f.context.planning.add(admin, "c", "b");
    expect(() => f.context.planning.add(admin, "a", "c")).toThrow("cycle");
    expect(f.context.planning.projectPlan(reader).order).toEqual(["a", "b", "c"]);
    expect(f.context.eventRepository.count("a")).toBe(1);
  });

  test("completing prerequisites releases dependent queued work", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.planning.add(admin, "second", "first");
    f.context.jobs.transition(admin, "first", { stage: "active", expectedRevision: 1, reason: "start" });
    f.context.jobs.transition(admin, "first", { stage: "complete", expectedRevision: 2, reason: "done" });
    expect(f.context.planning.blockers(reader, "second")).toEqual([]);
    expect(f.context.planning.ready(reader).map(job => job.id)).toEqual(["second"]);
  });

  test("removal is idempotent and restores independent readiness", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    f.context.planning.add(admin, "second", "first");
    expect(f.context.planning.remove(admin, "second", "first")).toBe(true);
    expect(f.context.planning.remove(admin, "second", "first")).toBe(false);
    expect(f.context.planning.ready(reader).map(job => job.id)).toEqual(["first", "second"]);
    expect(f.context.eventRepository.count("second")).toBe(3);
  });

  test("dependencies cannot cross projects", () => {
    using f = fixture();
    f.create();
    f.context.jobs.create(outsider, { id: "foreign", title: "Foreign", owner: "owner", project: "other" });
    expect(() => f.context.planning.add(admin, "job", "foreign")).toThrow("another project");
    expect(f.context.planning.projectPlan(reader).order).toEqual(["job"]);
    expect(f.context.eventRepository.count("job")).toBe(1);
  });

  test("write-only users can add an edge but cannot read project plans", () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    expect(f.context.planning.add(writer, "second", "first")).toBe(true);
    expect(() => f.context.planning.projectPlan(writer)).toThrow("permission");
    expect(() => f.context.planning.add(reader, "first", "second")).toThrow("permission");
  });

  test("planning HTTP routes expose layers, blockers and impact", async () => {
    using f = fixture();
    f.create("first");
    f.create("second");
    const added = await f.request("POST", "/jobs/second/dependencies", { requiresId: "first" });
    expect(added.status).toBe(201);
    expect(await added.json()).toEqual({ added: true });
    const result = await f.request("GET", "/planning", undefined, reader);
    expect(await result.json()).toMatchObject({ layers: [["first"], ["second"]] });
    const blocked = await f.request("GET", "/jobs/second/blockers", undefined, reader);
    expect(await blocked.json()).toMatchObject([{ id: "first" }]);
    const effect = await f.request("GET", "/jobs/first/impact", undefined, reader);
    expect(await effect.json()).toMatchObject({ dependents: ["second"] });
  });
});

describe("planning consistency across larger graphs", () => {
  test("all emitted dependencies precede their consumers in a wide acyclic graph", () => {
    const ids = Array.from({ length: 100 }, (_, index) => `node-${String(index).padStart(3, "0")}`);
    const edges = ids.flatMap((id, index) => {
      if (index === 0) return [];
      const parent = Math.floor((index - 1) / 2);
      return [{ jobId: id, requiresId: ids[parent]! }];
    });
    const result = plan([...ids].reverse(), [...edges].reverse());
    expect(result.order).toHaveLength(ids.length);
    expect(new Set(result.order).size).toBe(ids.length);
    for (const edge of edges) {
      expect(result.order.indexOf(edge.requiresId)).toBeLessThan(result.order.indexOf(edge.jobId));
    }
    expect(result.roots).toEqual([ids[0]!]);
    expect(result.layers[0]).toEqual([ids[0]!]);
  });

  test("a cycle in one disconnected component cannot silently drop that component", () => {
    const ids = ["safe-a", "safe-b", "cycle-a", "cycle-b"];
    const edges = [
      { jobId: "safe-b", requiresId: "safe-a" },
      { jobId: "cycle-a", requiresId: "cycle-b" },
      { jobId: "cycle-b", requiresId: "cycle-a" },
    ];
    expect(() => plan(ids, edges)).toThrow("dependency cycle");
    const graph = adjacency(ids, edges);
    expect(ancestors("safe-b", graph)).toEqual(["safe-a"]);
    expect(descendants("safe-a", graph)).toEqual(["safe-b"]);
  });

  test("dependency removal immediately changes transitive impact", () => {
    using f = fixture();
    f.create("a");
    f.create("b");
    f.create("c");
    f.context.planning.add(admin, "b", "a");
    f.context.planning.add(admin, "c", "b");
    expect(f.context.planning.jobImpact(reader, "a").dependents).toEqual(["b", "c"]);
    expect(f.context.planning.remove(admin, "c", "b")).toBe(true);
    expect(f.context.planning.jobImpact(reader, "a").dependents).toEqual(["b"]);
    expect(f.context.planning.jobImpact(reader, "c").prerequisites).toEqual([]);
    expect(f.context.planning.ready(reader).map(job => job.id)).toEqual(["a", "c"]);
  });
});

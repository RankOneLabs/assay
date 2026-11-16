import { conflict } from "./errors.ts";

export interface Edge {
  jobId: string;
  requiresId: string;
}

export interface Plan {
  order: string[];
  layers: string[][];
  roots: string[];
  leaves: string[];
}

/** Build adjacency once; readers never infer session state from graph membership. */
export function adjacency(ids: readonly string[], edges: readonly Edge[]): Map<string, Set<string>> {
  const result = new Map(ids.map(id => [id, new Set<string>()]));
  for (const edge of edges) {
    if (!result.has(edge.jobId) || !result.has(edge.requiresId)) {
      conflict("dependency references a job outside the plan");
    }
    result.get(edge.jobId)!.add(edge.requiresId);
  }
  return result;
}

/** Breadth-first traversal uses a cursor so wide dependency graphs remain linear. */
export function ancestors(id: string, graph: ReadonlyMap<string, ReadonlySet<string>>): string[] {
  if (!graph.has(id)) conflict("unknown graph root");
  const found = new Set<string>();
  const pending = [...graph.get(id)!];
  for (let cursor = 0; cursor < pending.length; cursor++) {
    const current = pending[cursor]!;
    if (found.has(current)) continue;
    found.add(current);
    pending.push(...graph.get(current) ?? []);
  }
  return [...found].sort();
}

export function descendants(id: string, graph: ReadonlyMap<string, ReadonlySet<string>>): string[] {
  const reversed = new Map<string, Set<string>>();
  for (const key of graph.keys()) reversed.set(key, new Set());
  for (const [job, requirements] of graph) {
    for (const requirement of requirements) reversed.get(requirement)!.add(job);
  }
  return ancestors(id, reversed);
}

/** Kahn's algorithm emits deterministic layers and rejects cycles without recursion. */
export function plan(ids: readonly string[], edges: readonly Edge[]): Plan {
  if (new Set(ids).size !== ids.length) conflict("duplicate jobs in plan");
  const graph = adjacency(ids, edges);
  const remaining = new Map([...graph].map(([id, needs]) => [id, needs.size]));
  const consumers = new Map(ids.map(id => [id, new Set<string>()]));
  for (const [job, requirements] of graph) {
    for (const requirement of requirements) consumers.get(requirement)!.add(job);
  }
  const roots = ids.filter(id => remaining.get(id) === 0).sort();
  const leaves = ids.filter(id => consumers.get(id)!.size === 0).sort();
  const layers: string[][] = [];
  const order: string[] = [];
  let ready = roots;
  while (ready.length) {
    layers.push(ready);
    order.push(...ready);
    const next: string[] = [];
    for (const id of ready) {
      for (const consumer of consumers.get(id)!) {
        const count = remaining.get(consumer)! - 1;
        remaining.set(consumer, count);
        if (count === 0) next.push(consumer);
      }
    }
    ready = next.sort();
  }
  if (order.length !== ids.length) {
    const blocked = ids.filter(id => remaining.get(id)! > 0).sort();
    conflict("dependency cycle", { blocked });
  }
  return { order, layers, roots, leaves };
}

export function impact(id: string, ids: readonly string[], edges: readonly Edge[]) {
  const graph = adjacency(ids, edges);
  return {
    id,
    prerequisites: ancestors(id, graph),
    dependents: descendants(id, graph),
    direct: [...graph.get(id) ?? []].sort(),
  };
}

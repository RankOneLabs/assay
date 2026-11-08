import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { Workflow } from "../../src/core-client/core-types";

// The pinned tests' authority fixture also opens a scratch Postgres database and the
// Rust core. These tests only read its sample workflows, so only that function ships.
const root = resolve(import.meta.dir, "../..");
export function sampleWorkflow(name: "review-loop" | "fan-out"): Workflow {
  return JSON.parse(readFileSync(resolve(root, "workflow-core/fixtures/bundles", `${name}.json`), "utf8")) as Workflow;
}

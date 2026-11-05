import { expect, test } from "bun:test";

import { compileWorkflowDefinition } from "../../../src/compiler/compile-workflow";
import { contextRequirementsOf, describeUnsatisfiedRequirements, unsatisfiedContextRequirements } from "../../../src/compiler/context-requirements";
import { resolveBinding, resolveBindingValue, resolveDelegatedExecution } from "../../../src/compiler/resolve-execution";
import type { DelegatedSessionDefinitionConfig } from "../../../src/domain/delegated-session";
import type { StageInstanceId, UnitId, WorkflowRunId } from "../../../src/domain/primitives";
import type { WorkflowGraph } from "../../../src/domain/workflow";
import { loadDevFlowV14 } from "../../../src/seed/dev-flow-v14";
import { bindableSchema, slotBindingSchema } from "../../../src/validation/slot-binding";

/**
 * Behaviour of bindings that declare no default, pinned at the checkpoint. These
 * hold before and after any change that adds optional context bindings.
 */

test("a context binding without a default parses to exactly its two fields", () => {
  const parsed = slotBindingSchema.parse({ from: "context", path: "/oakridge_url" });
  expect(parsed).toEqual({ from: "context", path: "/oakridge_url" });
  expect(Object.keys(parsed).sort()).toEqual(["from", "path"]);
  expect(bindableSchema.parse({ from: "context", path: "/x" })).toEqual({ from: "context", path: "/x" });
});

test("a context binding without a default keeps today's permissive path rule", () => {
  expect(slotBindingSchema.safeParse({ from: "context", path: "oakridge_url" }).success).toBe(true);
  expect(slotBindingSchema.safeParse({ from: "context", path: "" }).success).toBe(true);
});

test("other binding variants ignore and drop a stray default key", () => {
  expect(slotBindingSchema.parse({ from: "item", path: "/title", default: "x" })).toEqual({ from: "item", path: "/title" });
  expect(slotBindingSchema.parse({ from: "literal", value: "v", default: "x" })).toEqual({ from: "literal", value: "v" });
  expect(slotBindingSchema.parse({ from: "input", input_name: "brief", default: "x" })).toEqual({ from: "input", input_name: "brief", path: null });
});

test("a missing pointer without a default is still an error with the same detail", () => {
  expect(resolveBindingValue({ from: "context", path: "/oakridge_url" }, { inputs: {}, context: {}, item: null }))
    .toEqual({ ok: false, error: { operation: "resolve_execution", detail: "context pointer '/oakridge_url' not found" } });
  expect(resolveBinding({ from: "context", path: "/a/b" }, { inputs: {}, context: { a: {} }, item: null }))
    .toEqual({ ok: false, error: { operation: "resolve_execution", detail: "context pointer '/a/b' not found" } });
});

test("a present context value, null included, resolves as before", () => {
  expect(resolveBindingValue({ from: "context", path: "/planner_effort" }, { inputs: {}, context: { planner_effort: null }, item: null }))
    .toEqual({ ok: true, value: null });
  expect(resolveBinding({ from: "context", path: "/n" }, { inputs: {}, context: { n: 3 }, item: null })).toEqual({ ok: true, value: "3" });
});

test("a context binding without a default is still a launch requirement", () => {
  const graph = {
    stages: {
      a: { stage_type: "delegated_session", operator_role: null, inputs: [], outputs: [], config: { slot_bindings: { U: { from: "context", path: "/oakridge_url" } } } },
      b: { stage_type: "delegated_session", operator_role: null, inputs: [], outputs: [], config: { slot_bindings: { U: { from: "context", path: "/oakridge_url" }, M: { from: "context", path: "/model" } } } },
    },
    edges: [],
  } as unknown as WorkflowGraph;
  const requirements = contextRequirementsOf(graph);
  expect(requirements).toEqual([{ pointer: "/oakridge_url", stage_key: "a" }, { pointer: "/model", stage_key: "b" }]);
  expect(describeUnsatisfiedRequirements(unsatisfiedContextRequirements({}, requirements))).toBe("/oakridge_url (a), /model (b)");
});

test("the shipped definition compiles with its bindings unchanged and resolves as before", async () => {
  const loaded = await loadDevFlowV14();
  if (!loaded.ok) throw new Error(loaded.error.detail);
  const compiled = compileWorkflowDefinition(loaded.value);
  if (!compiled.ok) throw new Error(compiled.error.detail);
  const spec = compiled.value.stages.spec_analyzer!.executor.definition_config as DelegatedSessionDefinitionConfig;
  expect(spec.effort).toEqual({ from: "context", path: "/planner_effort" });
  expect(spec.slot_bindings.BRIEF_NOTES).toEqual({ from: "context", path: "/brief_notes" });
  const missing = resolveDelegatedExecution({
    definition: spec, environment: { inputs: {}, context: { planner_runtime: "claude-code" }, item: null },
    unit: { unit_id: "0" as UnitId, depends_on: [], parameters: {} }, stage_instance_id: "s" as StageInstanceId,
    prompt_template: "{{BRIEF_NOTES}}", run_id: "r" as WorkflowRunId, operator_role: "spec",
  });
  expect(missing).toEqual({ ok: false, error: { operation: "resolve_execution", detail: "context pointer '/brief_notes' not found" } });
});

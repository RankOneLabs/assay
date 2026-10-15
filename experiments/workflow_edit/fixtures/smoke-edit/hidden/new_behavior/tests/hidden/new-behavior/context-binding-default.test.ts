import { describe, expect, test } from "bun:test";

import { compileWorkflowDefinition } from "../../../src/compiler/compile-workflow";
import { contextRequirementsOf, unsatisfiedContextRequirements } from "../../../src/compiler/context-requirements";
import { resolveBinding, resolveBindingValue, resolveDelegatedExecution, type BindingEnvironment } from "../../../src/compiler/resolve-execution";
import type { DelegatedSessionDefinitionConfig, SlotBinding } from "../../../src/domain/delegated-session";
import type { StageInstanceId, UnitId, WorkflowRunId } from "../../../src/domain/primitives";
import type { WorkflowGraph } from "../../../src/domain/workflow";
import { delegatedSessionDefinitionSchema } from "../../../src/validation/delegated-session";
import { repositoryProvisioningDefinitionSchema } from "../../../src/validation/repository-provisioning";
import { bindableSchema, slotBindingSchema } from "../../../src/validation/slot-binding";
import { parseWorkflowDefinition } from "../../../src/validation/workflow-definition";

const ABSOLUTE_MESSAGE = "context binding with a default must use an absolute JSON pointer path";

const env = (context: BindingEnvironment["context"]): BindingEnvironment => ({ inputs: {}, context, item: null });

const graphOf = (stages: Readonly<Record<string, unknown>>): WorkflowGraph => ({
  stages: Object.fromEntries(Object.entries(stages).map(([key, config]) => [key,
    { stage_type: "delegated_session", operator_role: null, config, inputs: [], outputs: [] }])),
  edges: [],
} as unknown as WorkflowGraph);

describe("slotBindingSchema", () => {
  test("keeps a string default on a context binding", () => {
    const parsed = slotBindingSchema.safeParse({ from: "context", path: "/brief_notes", default: "(no notes)" });
    expect(parsed.success).toBe(true);
    expect(parsed.data).toEqual({ from: "context", path: "/brief_notes", default: "(no notes)" });
  });

  test("keeps a null default on a context binding", () => {
    const parsed = slotBindingSchema.safeParse({ from: "context", path: "/planner_effort", default: null });
    expect(parsed.success).toBe(true);
    expect(parsed.data).toEqual({ from: "context", path: "/planner_effort", default: null });
    expect(Object.prototype.hasOwnProperty.call(parsed.data, "default")).toBe(true);
  });

  test("keeps an empty-string default", () => {
    const parsed = slotBindingSchema.safeParse({ from: "context", path: "/notes", default: "" });
    expect(parsed.success).toBe(true);
    expect(parsed.data).toEqual({ from: "context", path: "/notes", default: "" });
  });

  test.each([[3], [true], [{ value: "x" }], [["x"]]])("rejects a non-string, non-null default %p", (value) => {
    expect(slotBindingSchema.safeParse({ from: "context", path: "/notes", default: value }).success).toBe(false);
  });

  test("rejects a defaulted binding whose path is not an absolute pointer", () => {
    const parsed = slotBindingSchema.safeParse({ from: "context", path: "planner_effort", default: null });
    expect(parsed.success).toBe(false);
    expect(parsed.error?.issues.map((issue) => issue.message)).toContain(ABSOLUTE_MESSAGE);
  });

  test("accepts a defaulted binding over the whole document", () => {
    expect(slotBindingSchema.safeParse({ from: "context", path: "", default: "x" }).success).toBe(true);
  });

  test("bindableSchema and the stage config schemas carry the default through", () => {
    expect(bindableSchema.parse({ from: "context", path: "/worker_model", default: "sonnet" }))
      .toEqual({ from: "context", path: "/worker_model", default: "sonnet" });
    const config = delegatedSessionDefinitionSchema.parse({
      runtime: { from: "context", path: "/worker_runtime", default: "claude-code" },
      prompt_template_path: "p.md",
      slot_bindings: { NOTES: { from: "context", path: "/brief_notes", default: "" } },
      workdir: { from: "literal", value: "/" },
      session_name: "s",
      effort: { from: "context", path: "/worker_effort", default: null },
    });
    expect(config.runtime).toEqual({ from: "context", path: "/worker_runtime", default: "claude-code" });
    expect(config.slot_bindings.NOTES).toEqual({ from: "context", path: "/brief_notes", default: "" });
    expect(config.effort).toEqual({ from: "context", path: "/worker_effort", default: null });
    const provisioning = repositoryProvisioningDefinitionSchema.parse({
      repositories: { from: "context", path: "/repositories" },
      base_branch: { from: "context", path: "/base_branch", default: "main" },
    });
    expect(provisioning.base_branch).toEqual({ from: "context", path: "/base_branch", default: "main" });
  });

  test("a stage config with a relative defaulted binding is rejected", () => {
    const parsed = delegatedSessionDefinitionSchema.safeParse({
      runtime: "claude-code", prompt_template_path: "p.md", slot_bindings: { X: { from: "context", path: "x", default: "y" } },
      workdir: { from: "literal", value: "/" }, session_name: "s",
    });
    expect(parsed.success).toBe(false);
  });
});

describe("resolveBindingValue", () => {
  const notes: SlotBinding = { from: "context", path: "/brief_notes", default: "(no notes)" };

  test("falls back to the default when the pointer does not resolve", () => {
    expect(resolveBindingValue(notes, env({}))).toEqual({ ok: true, value: "(no notes)" });
    expect(resolveBindingValue({ from: "context", path: "/a/b/c", default: "deep" }, env({ a: { b: 1 } }))).toEqual({ ok: true, value: "deep" });
  });

  test("a null default resolves to null", () => {
    expect(resolveBindingValue({ from: "context", path: "/planner_effort", default: null }, env({}))).toEqual({ ok: true, value: null });
  });

  test("the context value wins whenever the pointer resolves", () => {
    expect(resolveBindingValue(notes, env({ brief_notes: "ship it" }))).toEqual({ ok: true, value: "ship it" });
    expect(resolveBindingValue(notes, env({ brief_notes: "" }))).toEqual({ ok: true, value: "" });
    expect(resolveBindingValue(notes, env({ brief_notes: { a: [1] } }))).toEqual({ ok: true, value: { a: [1] } });
  });

  test("an explicit null in the context is a value, not an absence", () => {
    expect(resolveBindingValue(notes, env({ brief_notes: null }))).toEqual({ ok: true, value: null });
  });

  test("resolveBinding renders defaults like context values", () => {
    expect(resolveBinding(notes, env({}))).toEqual({ ok: true, value: "(no notes)" });
    expect(resolveBinding({ from: "context", path: "/x", default: null }, env({}))).toEqual({ ok: true, value: "null" });
  });
});

describe("resolveDelegatedExecution", () => {
  const unit = { unit_id: "0" as UnitId, depends_on: [], parameters: {} };
  const base = {
    unit, stage_instance_id: "stage-1" as StageInstanceId, run_id: "run-1" as WorkflowRunId, operator_role: "spec" as const,
    prompt_template: "Notes: {{NOTES}} | Title: {{TITLE}}",
  };
  const definition: DelegatedSessionDefinitionConfig = {
    runtime: { from: "context", path: "/planner_runtime", default: "codex" },
    prompt_template_path: "dev-flow/spec_analyzer_v2.md",
    slot_bindings: { NOTES: { from: "context", path: "/brief_notes", default: "(no notes)" }, TITLE: { from: "context", path: "/title" } },
    workdir: { from: "context", path: "/workdir", default: "/srv/work" },
    session_name: "spec-{{STAGE_INSTANCE_ID}}",
    model: { from: "context", path: "/planner_model", default: "sonnet" },
    effort: { from: "context", path: "/planner_effort", default: null },
  };

  test("defaults fill every binding position the context leaves out", () => {
    const result = resolveDelegatedExecution({ ...base, definition, environment: env({ title: "Spec" }) });
    expect(result).toEqual({ ok: true, value: expect.objectContaining({
      runtime: "codex", rendered_prompt: "Notes: (no notes) | Title: Spec", workdir: "/srv/work", model: "sonnet", effort: null,
    }) });
  });

  test("context values override every default", () => {
    const result = resolveDelegatedExecution({ ...base, definition, environment: env({
      title: "Spec", brief_notes: "real notes", planner_runtime: "claude-code", workdir: "/repo", planner_model: "opus", planner_effort: "high",
    }) });
    expect(result).toEqual({ ok: true, value: expect.objectContaining({
      runtime: "claude-code", rendered_prompt: "Notes: real notes | Title: Spec", workdir: "/repo", model: "opus", effort: "high",
    }) });
  });

  test("a mandatory binding next to defaulted ones still fails when missing", () => {
    const result = resolveDelegatedExecution({ ...base, definition, environment: env({}) });
    expect(result).toEqual({ ok: false, error: { operation: "resolve_execution", detail: "context pointer '/title' not found" } });
  });

  test("defaults apply to fan-out item bindings and worktree fields", () => {
    const fanOut: DelegatedSessionDefinitionConfig = {
      ...definition,
      slot_bindings: {},
      fan_out: {
        over: { from: "input", input_name: "brief" }, unit_id_path: "/unit_id",
        item_bindings: { NOTES: { from: "context", path: "/cohort_notes", default: "none" }, TITLE: { from: "item", path: "/title" } },
        worktree: { branch_name: "cohort/{{UNIT_ID}}", worktree_subdir: "{{UNIT_ID}}", base_ref: { from: "context", path: "/base_branch", default: "main" } },
      },
    };
    const result = resolveDelegatedExecution({ ...base, definition: fanOut, unit: { unit_id: "c1" as UnitId, depends_on: [], parameters: { title: "Cohort one" } }, environment: env({}) });
    expect(result).toEqual({ ok: true, value: expect.objectContaining({
      rendered_prompt: "Notes: none | Title: Cohort one",
      worktree: { branchName: "cohort/c1", worktreeSubdir: "c1", baseRef: "main" },
    }) });
  });
});

describe("contextRequirementsOf", () => {
  test("a defaulted context binding is not a launch requirement", () => {
    const graph = graphOf({ build: {
      effort: { from: "context", path: "/planner_effort", default: null },
      slot_bindings: { NOTES: { from: "context", path: "/brief_notes", default: "" }, URL: { from: "context", path: "/oakridge_url" } },
    } });
    expect(contextRequirementsOf(graph)).toEqual([{ pointer: "/oakridge_url", stage_key: "build" }]);
  });

  test("a pointer is attributed to the first stage that reads it without a default", () => {
    const graph = graphOf({
      spec_analyzer: { slot_bindings: { URL: { from: "context", path: "/oakridge_url", default: "http://localhost" } } },
      plan_writer: { slot_bindings: { URL: { from: "context", path: "/oakridge_url" } } },
      brief_writer: { slot_bindings: { URL: { from: "context", path: "/oakridge_url" } } },
    });
    expect(contextRequirementsOf(graph)).toEqual([{ pointer: "/oakridge_url", stage_key: "plan_writer" }]);
  });

  test("one mandatory read in a stage outweighs a defaulted read of the same pointer", () => {
    const graph = graphOf({ build: { slot_bindings: {
      A: { from: "context", path: "/oakridge_url", default: "x" },
      B: { from: "context", path: "/oakridge_url" },
    } } });
    expect(contextRequirementsOf(graph)).toEqual([{ pointer: "/oakridge_url", stage_key: "build" }]);
  });

  test("a launch missing only defaulted keys is satisfied", () => {
    const graph = graphOf({ build: { slot_bindings: {
      NOTES: { from: "context", path: "/brief_notes", default: "" },
      URL: { from: "context", path: "/oakridge_url" },
    } } });
    expect(unsatisfiedContextRequirements({ oakridge_url: "http://oakridge" }, contextRequirementsOf(graph))).toEqual([]);
    expect(unsatisfiedContextRequirements({}, contextRequirementsOf(graph))).toEqual([{ pointer: "/oakridge_url", stage_key: "build" }]);
  });
});

describe("end to end through definition parsing and compilation", () => {
  const definitionJson = (notesBinding: unknown) => ({
    id: "8d0f7a4e-2b7c-4c1e-9f3a-5e6d7c8b9a01",
    name: "defaults-smoke",
    version: 1,
    created_at: "2026-10-01T00:00:00Z",
    graph: {
      stages: {
        writer: {
          stage_type: "delegated_session",
          operator_role: "spec",
          config: {
            runtime: { from: "context", path: "/planner_runtime" },
            prompt_template_path: "dev-flow/spec_analyzer_v2.md",
            slot_bindings: { NOTES: notesBinding },
            workdir: { from: "literal", value: "/" },
            session_name: "writer-{{STAGE_INSTANCE_ID}}",
            effort: { from: "context", path: "/planner_effort", default: null },
          },
          inputs: [],
          outputs: [{ name: "spec_analysis", artifact_type: "dev.spec_analysis" }],
        },
      },
      edges: [],
    },
  });

  test("defaults survive parsing and compilation and are used at resolution", () => {
    const parsed = parseWorkflowDefinition(definitionJson({ from: "context", path: "/brief_notes", default: "(no notes)" }));
    if (!parsed.ok) throw new Error(parsed.error.detail);
    expect(contextRequirementsOf(parsed.value.graph)).toEqual([{ pointer: "/planner_runtime", stage_key: "writer" }]);
    const compiled = compileWorkflowDefinition(parsed.value);
    if (!compiled.ok) throw new Error(compiled.error.detail);
    const config = compiled.value.stages.writer!.executor.definition_config as DelegatedSessionDefinitionConfig;
    expect(config.slot_bindings.NOTES).toEqual({ from: "context", path: "/brief_notes", default: "(no notes)" });
    expect(config.effort).toEqual({ from: "context", path: "/planner_effort", default: null });
    const resolved = resolveDelegatedExecution({
      definition: config, environment: env({ planner_runtime: "claude-code" }), unit: { unit_id: "0" as UnitId, depends_on: [], parameters: {} },
      stage_instance_id: "stage-9" as StageInstanceId, prompt_template: "{{NOTES}}", run_id: "run-9" as WorkflowRunId, operator_role: "spec",
    });
    expect(resolved).toEqual({ ok: true, value: expect.objectContaining({ rendered_prompt: "(no notes)", effort: null, session_name: "writer-stage-9" }) });
  });

  test("a defaulted binding with a relative path is refused at definition time", () => {
    const parsed = parseWorkflowDefinition(definitionJson({ from: "context", path: "brief_notes", default: "(no notes)" }));
    expect(parsed.ok).toBe(false);
    if (parsed.ok) return;
    expect(parsed.error.detail).toContain(ABSOLUTE_MESSAGE);
  });
});

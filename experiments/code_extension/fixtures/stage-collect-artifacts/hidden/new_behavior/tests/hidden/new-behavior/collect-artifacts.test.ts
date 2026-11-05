import { expect, test } from "bun:test";
import { compileWorkflowDefinition } from "../../../src/compiler/compile-workflow";
import { loadDevFlowV14 } from "../../../src/seed/dev-flow-v14";

const INPUT_BINDING = { from: "input", input_name: "items", path: "/entries" };
const CONTEXT_BINDING = { from: "context", path: "/repositories" };

const definition = async (config: unknown, attention?: "required") => {
  const loaded = await loadDevFlowV14();
  if (!loaded.ok) throw new Error(loaded.error.detail);
  return {
    ...loaded.value,
    graph: {
      stages: {
        collect: {
          ...loaded.value.graph.stages.spec_analyzer!,
          stage_type: "collect_artifacts",
          operator_role: null,
          config,
          inputs: [],
          outputs: [{ name: "value", artifact_type: "dev.value", ...(attention ? { attention } : {}) }],
        },
      },
      edges: [],
    },
  };
};

const compile = async (config: unknown, attention?: "required") =>
  compileWorkflowDefinition((await definition(config, attention)) as never);

test("reachability: collect_artifacts resolves through normal dispatch", async () => {
  const compiled = await compile({ over: INPUT_BINDING, id_path: "/id" });
  if (!compiled.ok) expect(compiled.error.detail).not.toContain("unregistered stage type");
});

test.each([
  ["an input binding", INPUT_BINDING],
  ["a context binding", CONTEXT_BINDING],
])("semantics: materializes an artifact collection over %s", async (_label, over) => {
  const compiled = await compile({ over, id_path: "/meta/id" });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.collect?.materialization).toEqual({
    kind: "artifact_collection", over, id_path: "/meta/id",
  });
});

test("semantics: the executor keeps the configuration", async () => {
  const compiled = await compile({ over: INPUT_BINDING, id_path: "/id" });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.collect?.executor).toEqual({
    executor_type: "collect_artifacts",
    definition_config: { over: INPUT_BINDING, id_path: "/id" },
  });
});

test("semantics: outputs release immediately", async () => {
  const compiled = await compile({ over: INPUT_BINDING, id_path: "/id" });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.collect?.outputs[0]?.release).toEqual({ kind: "immediate" });
});

test.each([
  ["a missing binding", { id_path: "/id" }],
  ["a malformed binding", { over: { from: "input" }, id_path: "/id" }],
  ["a literal binding", { over: { from: "literal", value: "items" }, id_path: "/id" }],
  ["an item binding", { over: { from: "item", path: "/entries" }, id_path: "/id" }],
  ["a missing id_path", { over: INPUT_BINDING }],
  ["a relative id_path", { over: INPUT_BINDING, id_path: "id" }],
  ["a root id_path", { over: INPUT_BINDING, id_path: "/" }],
  ["an empty id_path", { over: INPUT_BINDING, id_path: "" }],
  ["a non-object configuration", "items"],
])("semantics: rejects %s with a stage-scoped error", async (_label, config) => {
  const compiled = await compile(config);
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.stage_key).toBe("collect");
});

test("semantics: rejects unknown fields", async () => {
  const compiled = await compile({ over: INPUT_BINDING, id_path: "/id", max_parallel: 2 });
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.stage_key).toBe("collect");
});

test("semantics: required attention cannot continue immediately", async () => {
  const compiled = await compile({ over: INPUT_BINDING, id_path: "/id" }, "required");
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.detail).toContain("required attention");
});

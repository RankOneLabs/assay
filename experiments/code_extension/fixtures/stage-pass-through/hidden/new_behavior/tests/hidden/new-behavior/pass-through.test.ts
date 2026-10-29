import { expect, test } from "bun:test";
import { compileWorkflowDefinition } from "../../../src/compiler/compile-workflow";
import { loadDevFlowV14 } from "../../../src/seed/dev-flow-v14";

const passThroughDefinition = async (config: { readonly [key: string]: string }) => {
  const loaded = await loadDevFlowV14();
  if (!loaded.ok) throw new Error(loaded.error.detail);
  return {
    ...loaded.value,
    graph: {
      stages: {
        pass: {
          ...loaded.value.graph.stages.spec_analyzer!,
          stage_type: "pass_through",
          operator_role: null,
          config,
          inputs: [],
          outputs: [{ name: "value", artifact_type: "dev.value" }],
        },
      },
      edges: [],
    },
  };
};

test("pass_through compiles without injected registration", async () => {
  const compiled = compileWorkflowDefinition(await passThroughDefinition({}));
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.pass?.materialization).toEqual({ kind: "scalar" });
  expect(compiled.value.stages.pass?.outputs[0]?.release).toEqual({ kind: "immediate" });
  expect(compiled.value.stages.pass?.executor).toEqual({ executor_type: "pass_through", definition_config: {} });
  expect(compiled.value.source_stages).toEqual(["pass"]);
});

test("pass_through rejects nonempty config", async () => {
  const compiled = compileWorkflowDefinition(await passThroughDefinition({ unexpected: "value" }));
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.stage_key).toBe("pass");
});

import { expect, test } from "bun:test";
import { compileWorkflowDefinition } from "../../../src/compiler/compile-workflow";
import { loadDevFlowV14 } from "../../../src/seed/dev-flow-v14";

const definition = async (config: unknown, attention?: "required") => {
  const loaded = await loadDevFlowV14();
  if (!loaded.ok) throw new Error(loaded.error.detail);
  return {
    ...loaded.value,
    graph: {
      stages: {
        report: {
          ...loaded.value.graph.stages.spec_analyzer!,
          stage_type: "status_report",
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

test("reachability: status_report resolves through normal dispatch", async () => {
  const compiled = await compile({ channel: "ops", severity: "warning", max_items: 5 });
  if (!compiled.ok) expect(compiled.error.detail).not.toContain("unregistered stage type");
});

test("semantics: explicit configuration is preserved", async () => {
  const compiled = await compile({ channel: "ops", severity: "error", max_items: 5 });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.report?.executor).toEqual({
    executor_type: "status_report",
    definition_config: { channel: "ops", severity: "error", max_items: 5 },
  });
});

test("semantics: omitted fields take their documented defaults", async () => {
  const compiled = await compile({ channel: "ops" });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.report?.executor.definition_config).toEqual({
    channel: "ops", severity: "info", max_items: 20,
  });
});

test.each([
  ["info"],
  ["warning"],
  ["error"],
])("semantics: accepts severity %s and defaults max_items alone", async (severity) => {
  const compiled = await compile({ channel: "ops", severity });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.report?.executor.definition_config).toEqual({
    channel: "ops", severity, max_items: 20,
  });
});

test("semantics: defaults severity alone", async () => {
  const compiled = await compile({ channel: "ops", max_items: 5 });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.report?.executor.definition_config).toEqual({
    channel: "ops", severity: "info", max_items: 5,
  });
});

test("semantics: one scalar unit releases outputs immediately", async () => {
  const compiled = await compile({ channel: "ops" });
  expect(compiled.ok).toBe(true);
  if (!compiled.ok) return;
  expect(compiled.value.stages.report?.materialization).toEqual({ kind: "scalar" });
  expect(compiled.value.stages.report?.outputs[0]?.release).toEqual({ kind: "immediate" });
  expect(compiled.value.source_stages).toEqual(["report"]);
});

test.each([
  ["a missing channel", {}],
  ["an empty channel", { channel: "" }],
  ["a non-string channel", { channel: 7 }],
  ["an unknown severity", { channel: "ops", severity: "critical" }],
  ["a zero max_items", { channel: "ops", max_items: 0 }],
  ["a fractional max_items", { channel: "ops", max_items: 1.5 }],
  ["a string max_items", { channel: "ops", max_items: "5" }],
  ["a non-object configuration", "ops"],
])("semantics: rejects %s with a stage-scoped error", async (_label, config) => {
  const compiled = await compile(config);
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.stage_key).toBe("report");
});

test("semantics: rejects unknown fields", async () => {
  const compiled = await compile({ channel: "ops", retries: 3 });
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.stage_key).toBe("report");
});

test("semantics: required attention cannot continue immediately", async () => {
  const compiled = await compile({ channel: "ops" }, "required");
  expect(compiled.ok).toBe(false);
  if (!compiled.ok) expect(compiled.error.detail).toContain("required attention");
});

import { expect, test } from "bun:test";
import { DEFAULT_MAX_START_ATTEMPTS, DEFAULT_PROVIDER_DEADLINE_MS, decodeEffectInstruction, selectEffectInstruction, type EffectInstruction,
  type RunWorkerAction } from "../../../src/domain/effect-instruction";
import type { RunId } from "../../../src/domain/primitives";
import { parseRunConfig, selectWorkerSessionSettings, type RunConfig } from "../../../src/domain/run-config";
import { parseLaunchRequest } from "../../../src/http/ingress";
import { sampleWorkflow } from "../../visible/sample-workflow";

const MINUTE = 60_000;
const writer: RunWorkerAction = { kind: "run_worker", unit: "run-1/document", worker: "writer", mode: { kind: "initial" }, cause: { kind: "missing" } };
const runtime = { harness: "codex", model: "gpt-5.5" };
const defaults = { deadline_ms: DEFAULT_PROVIDER_DEADLINE_MS, max_start_attempts: DEFAULT_MAX_START_ATTEMPTS };

function launchConfig(sessions: unknown): RunConfig | null {
  const launched = parseLaunchRequest({ request_id: "r1", definition_id: "0".repeat(64), input: {}, config: { sessions } });
  if (!launched.ok) throw new Error("launch refused");
  return launched.value.config ?? null;
}

function instruction(config: RunConfig | null): EffectInstruction {
  const selected = selectEffectInstruction({ run_id: "run-1" as RunId, workflow: sampleWorkflow("review-loop"), stage: "document", config,
    action: writer, seq: 0, prompts: { "review-loop/write.md": "a".repeat(64), "review-loop/revise.md": "b".repeat(64) },
    resolved: { action_id: "action-initial", inputs: { topic: "Oakridge", critique: null }, feedback: [] } });
  if (!selected.ok) throw new Error(selected.error.detail);
  return selected.value;
}

/** The instruction as the executor reads it back from its stored JSON payload. */
function stored(value: EffectInstruction): EffectInstruction {
  const decoded = decodeEffectInstruction(JSON.parse(JSON.stringify(value)));
  if (!decoded.ok) throw new Error(decoded.error.detail);
  return decoded.value;
}

const budgetOf = (value: EffectInstruction) => ({ deadline_ms: value.deadline_ms, max_start_attempts: value.max_start_attempts });
const launched = (settings: object) => instruction(launchConfig({ document: { writer: { ...runtime, ...settings } } }));

test("reachability: a launched worker's deadline_ms reaches its effect instruction", () => {
  expect(launched({ deadline_ms: 30 * MINUTE }).deadline_ms).toBe(30 * MINUTE);
});

test("reachability: a launched worker's max_start_attempts reaches its effect instruction", () => {
  expect(launched({ max_start_attempts: 7 }).max_start_attempts).toBe(7);
});

test("reachability: the budget survives the stored instruction the executor decodes", () => {
  expect(budgetOf(stored(launched({ effort: "high", deadline_ms: 45 * MINUTE, max_start_attempts: 5 }))))
    .toEqual({ deadline_ms: 45 * MINUTE, max_start_attempts: 5 });
});

test("semantics: a budget below the defaults lowers them", () => {
  expect(budgetOf(stored(launched({ deadline_ms: 30_000, max_start_attempts: 1 })))).toEqual({ deadline_ms: 30_000, max_start_attempts: 1 });
});

test("semantics: setting one budget field keeps the other's default", () => {
  expect([budgetOf(launched({ deadline_ms: 30 * MINUTE })), budgetOf(launched({ max_start_attempts: 7 }))])
    .toEqual([{ ...defaults, deadline_ms: 30 * MINUTE }, { ...defaults, max_start_attempts: 7 }]);
});

test("semantics: a worker without a budget keeps the defaults, even when its stage sets one for another worker", () => {
  const value = stored(instruction(launchConfig({ document: { writer: runtime, critic: { ...runtime, deadline_ms: 30 * MINUTE, max_start_attempts: 7 } } })));
  expect(budgetOf(value)).toEqual(defaults);
});

test("semantics: the parser keeps the budget beside the runtime", () => {
  expect(parseRunConfig({ sessions: { document: { writer: { ...runtime, effort: "high", deadline_ms: 90_000, max_start_attempts: 4 } } } }) as unknown)
    .toEqual({ sessions: { document: { writer: { ...runtime, effort: "high", deadline_ms: 90_000, max_start_attempts: 4 } } } });
});

test("semantics: a budget that is not a positive integer makes the configuration malformed", () => {
  const bad = [0, -1, 1.5, "60000", null, Number.POSITIVE_INFINITY];
  const configs = bad.flatMap((value) => [{ deadline_ms: value }, { max_start_attempts: value }])
    .map((budget) => ({ sessions: { document: { writer: { ...runtime, ...budget } } } }));
  expect([configs.map((config) => parseRunConfig(config)),
    configs.map((config) => parseLaunchRequest({ request_id: "r1", definition_id: "0".repeat(64), input: {}, config }).ok)])
    .toEqual([configs.map(() => null), configs.map(() => false)]);
});

test("semantics: harness and model stay required", () => {
  expect(parseRunConfig({ sessions: { document: { writer: { deadline_ms: 90_000, max_start_attempts: 4 } } } })).toBeNull();
});

test("semantics: an unset budget adds no key to the configuration or the instruction's settings", () => {
  const config = launchConfig({ document: { writer: runtime } });
  const value = instruction(config);
  expect([config, value.worker.kind === "agent" ? value.worker.settings : "code", budgetOf(value)]).toEqual([
    { sessions: { document: { writer: { ...runtime, effort: null } } } }, { ...runtime, effort: null }, defaults]);
  expect(Object.keys(value.worker.kind === "agent" ? value.worker.settings ?? {} : {}).sort()).toEqual(["effort", "harness", "model"]);
});

test("semantics: a declared runtime fallback carries no budget", () => {
  const settings = selectWorkerSessionSettings({ sessions: { document: { critic: { ...runtime, effort: null, deadline_ms: 90_000 } as never } } },
    { stage: "document", worker: "writer" }, { harness: "codex", model: "gpt-5.5" });
  expect(settings).toEqual({ harness: "codex", model: "gpt-5.5", effort: null });
  expect(Object.keys(settings ?? {}).sort()).toEqual(["effort", "harness", "model"]);
});

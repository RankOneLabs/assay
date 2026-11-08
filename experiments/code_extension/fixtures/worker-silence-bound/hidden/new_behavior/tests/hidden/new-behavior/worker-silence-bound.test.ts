import { expect, test } from "bun:test";
import { KbblClient } from "../../../src/adapters/kbbl";
import { decodeEffectInstruction, selectEffectInstruction, type EffectInstruction, type RunWorkerAction } from "../../../src/domain/effect-instruction";
import type { RunId } from "../../../src/domain/primitives";
import { parseRunConfig, selectWorkerSessionSettings, type RunConfig } from "../../../src/domain/run-config";
import { createAgentProvider, type AgentProviderConfig } from "../../../src/effects/agent-provider";
import { resolveObserve } from "../../../src/effects/outcomes";
import type { ExternalHandle } from "../../../src/effects/provider";
import { parseLaunchRequest } from "../../../src/http/ingress";
import { sampleWorkflow } from "../../visible/sample-workflow";

const LAST_ACTIVITY = Date.parse("2026-10-12T12:00:00.000Z");
const MINUTE = 60_000;
const session: ExternalHandle = { kind: "kbbl_session", session_id: "sid-1" };
const writer: RunWorkerAction = { kind: "run_worker", unit: "run-1/document", worker: "writer", mode: { kind: "initial" }, cause: { kind: "missing" } };
const runtime = { harness: "codex", model: "gpt-5.5" };

/** A kbbl whose session is still prompting and was last active at LAST_ACTIVITY. */
async function silentKbbl(input: string | URL | Request, init: RequestInit = {}): Promise<Response> {
  void input;
  const snapshot = { sid: "sid-1", status: "live", lastActivityTs: new Date(LAST_ACTIVITY).toISOString() };
  return (init.method ?? "GET") === "GET"
    ? Response.json({ pending: true, session: snapshot }, { status: 202 })
    : Response.json({ accepted: true, status: "prompting" });
}

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

async function observeAfter(value: EffectInstruction, silent_ms: number, provider: Partial<AgentProviderConfig> = {}) {
  const config: AgentProviderConfig = { kbbl: new KbblClient({ base_url: "http://kbbl.test/", fetch: silentKbbl }), publication_key: "key",
    publish_base_url: "http://oakridge.test", default_workdir: "/srv/agents", now: () => LAST_ACTIVITY + silent_ms, ...provider };
  const observed = resolveObserve(await createAgentProvider(config).observe(value, { task: "t" }, session));
  return observed.kind === "refused" ? observed.failure.code : observed.kind;
}

test("reachability: a launched worker bound keeps its session running past the provider default", async () => {
  const config = launchConfig({ document: { writer: { ...runtime, max_silent_ms: 2 * 60 * MINUTE } } });
  expect(await observeAfter(instruction(config), 45 * MINUTE)).toBe("running");
});

test("reachability: the bound survives the stored instruction the executor decodes", async () => {
  const config = launchConfig({ document: { writer: { ...runtime, max_silent_ms: 2 * 60 * MINUTE } } });
  expect(await observeAfter(stored(instruction(config)), 45 * MINUTE)).toBe("running");
});

test("semantics: a worker bound below the provider's ends the session sooner", async () => {
  const config = launchConfig({ document: { writer: { ...runtime, max_silent_ms: 2 * MINUTE } } });
  expect(await observeAfter(stored(instruction(config)), 5 * MINUTE)).toBe("executor_silent_timeout");
});

test("semantics: the bound is in milliseconds", async () => {
  const value = stored(instruction(launchConfig({ document: { writer: { ...runtime, max_silent_ms: 2 * MINUTE } } })));
  expect([await observeAfter(value, 90_000), await observeAfter(value, 150_000)]).toEqual(["running", "executor_silent_timeout"]);
});

test("semantics: the worker's bound also overrides a configured provider bound", async () => {
  const value = stored(instruction(launchConfig({ document: { writer: { ...runtime, max_silent_ms: 2 * 60 * MINUTE } } })));
  expect(await observeAfter(value, 45 * MINUTE, { max_silent_ms: 10 * MINUTE })).toBe("running");
});

test("semantics: a worker without a bound keeps the provider's, even when its stage sets one for another worker", async () => {
  const value = stored(instruction(launchConfig({ document: { writer: runtime, critic: { ...runtime, max_silent_ms: 2 * 60 * MINUTE } } })));
  expect([await observeAfter(value, 45 * MINUTE), await observeAfter(value, 5 * MINUTE, { max_silent_ms: 2 * MINUTE })])
    .toEqual(["executor_silent_timeout", "executor_silent_timeout"]);
});

test("semantics: the parser keeps the bound beside the runtime", () => {
  expect(parseRunConfig({ sessions: { document: { writer: { ...runtime, effort: "high", max_silent_ms: 90_000 } } } }) as unknown)
    .toEqual({ sessions: { document: { writer: { ...runtime, effort: "high", max_silent_ms: 90_000 } } } });
});

test("semantics: a bound that is not a positive integer makes the configuration malformed", () => {
  const bad = [0, -1, 1.5, "60000", null, Number.POSITIVE_INFINITY];
  const launched = bad.map((max_silent_ms) =>
    parseLaunchRequest({ request_id: "r1", definition_id: "0".repeat(64), input: {}, config: { sessions: { document: { writer: { ...runtime, max_silent_ms } } } } }).ok);
  expect([bad.map((max_silent_ms) => parseRunConfig({ sessions: { document: { writer: { ...runtime, max_silent_ms } } } })), launched])
    .toEqual([bad.map(() => null), bad.map(() => false)]);
});

test("semantics: harness and model stay required", () => {
  expect(parseRunConfig({ sessions: { document: { writer: { max_silent_ms: 90_000 } } } })).toBeNull();
});

test("semantics: an unset bound adds no key to the configuration or the instruction", () => {
  const config = launchConfig({ document: { writer: runtime } });
  const value = instruction(config);
  expect([config, value.worker.kind === "agent" ? value.worker.settings : "code"]).toEqual([
    { sessions: { document: { writer: { ...runtime, effort: null } } } }, { ...runtime, effort: null }]);
  expect(Object.keys(value.worker.kind === "agent" ? value.worker.settings ?? {} : {}).sort()).toEqual(["effort", "harness", "model"]);
});

test("semantics: a declared runtime fallback carries no bound", () => {
  const settings = selectWorkerSessionSettings({ sessions: { document: { critic: { ...runtime, effort: null, max_silent_ms: 90_000 } as never } } },
    { stage: "document", worker: "writer" }, { harness: "codex", model: "gpt-5.5" });
  expect(settings).toEqual({ harness: "codex", model: "gpt-5.5", effort: null });
  expect(Object.keys(settings ?? {}).sort()).toEqual(["effort", "harness", "model"]);
});

import { afterEach, expect, test } from "bun:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Hono } from "hono";
import type { Database } from "bun:sqlite";

import { loadAgentProfiles } from "../../../src/acp/agent-profile";
import { AcpControllerRegistry } from "../../../src/acp/controller-registry";
import { AcpProcessSupervisor } from "../../../src/acp/process-supervisor";
import { AcpSessionService } from "../../../src/acp/session-service";
import { AcpSessionStore, startSpecHash } from "../../../src/acp/store";
import { ok, type AcpSessionStartSpec, type KbblSessionId } from "../../../src/acp/types";
import { KbblConfigSchema } from "../../../src/config";
import { openTestDb } from "../../../src/db/test-db";
import { createApp } from "../../../src/server/app";
import { mountSessionsRoutes } from "../../../src/server/handlers/sessions";

// The pinned fake ACP agent advertises two models (fake-small, current by default;
// fake-large) and two efforts (low, current by default; high).
const FIXTURE = join(import.meta.dir, "../../../src/acp/__fixtures__/fake-acp-agent.ts");
const DEFAULTS = { default_model: "fake-large", default_effort: "high" };

interface Kbbl {
  service: AcpSessionService;
  store: AcpSessionStore;
  registry: AcpControllerRegistry;
  db: Database;
}

const open: AcpSessionService[] = [];
afterEach(async () => {
  for (const service of open.splice(0)) await service.shutdown();
});

async function dirs(): Promise<{ stateDir: string; workdir: string }> {
  return {
    stateDir: await mkdtemp(join(tmpdir(), "default-model-state-")),
    workdir: await mkdtemp(join(tmpdir(), "default-model-work-")),
  };
}

/** A config.acp.agents entry that launches the fake agent. */
function fakeAgent(stateDir: string, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return { command: process.execPath, args: [FIXTURE], env_policy: { set: { FAKE_ACP_BEHAVIOR: "happy", FAKE_ACP_STATE_DIR: stateDir } }, ...extra };
}

/** The service as server.ts composes it: profiles loaded from the parsed config. */
function kbbl(acp: unknown, db: Database = openTestDb()): Kbbl {
  const parsed = KbblConfigSchema.parse({ acp }).acp;
  const store = new AcpSessionStore(db);
  const registry = new AcpControllerRegistry();
  const service = new AcpSessionService({
    store,
    controllers: registry,
    profiles: loadAgentProfiles(parsed),
    supervisor: new AcpProcessSupervisor({ graceful_kill_ms: 1000, hard_kill_ms: 1000 }),
    worktrees: { resolve: async (_sid, spec) => ok({ worktree_path: spec.workdir, worktree_branch: null, worktree_base_ref: null, parent_sid: null }) },
    config: { default_agent: parsed.default_agent, graceful_kill_ms: 1000, idle_child_ttl_ms: parsed.idle_child_ttl_ms, live_event_buffer: parsed.live_event_buffer },
  });
  open.push(service);
  return { service, store, registry, db };
}

/** What the running agent reports as current for a config category. */
function live(registry: AcpControllerRegistry, sid: string, category: "model" | "thought_level"): unknown {
  return registry.getLive(sid as KbblSessionId)?.liveConfigOptions.find((option) => option.category === category)?.currentValue ?? null;
}

function requested(target: Kbbl, sid: string) {
  const row = target.store.getSession(sid as KbblSessionId);
  return { model: row?.requested_model, effort: row?.requested_effort, live: [live(target.registry, sid, "model"), live(target.registry, sid, "thought_level")] };
}

async function ensure(target: Kbbl, key: string, spec: AcpSessionStartSpec): Promise<string> {
  const ensured = await target.service.ensureResumableSession(key, spec);
  if (!ensured.ok) throw new Error(`ensure failed: ${ensured.error.code} ${ensured.error.detail}`);
  return ensured.value.session.sid;
}

async function create(target: Kbbl, spec: AcpSessionStartSpec): Promise<string> {
  const created = await target.service.createSession(spec);
  if (!created.ok) throw new Error(`create failed: ${created.error.code} ${created.error.detail}`);
  return created.value.sid;
}

async function send(app: Hono, method: string, path: string, body: unknown): Promise<{ status: number; body: Record<string, unknown> }> {
  const res = await app.request(path, { method, headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  return { status: res.status, body: (await res.json()) as Record<string, unknown> };
}

async function config(acp: unknown): Promise<Array<Record<string, unknown>>> {
  const parsed = KbblConfigSchema.parse({ acp });
  const pwaDistDir = await mkdtemp(join(tmpdir(), "default-model-pwa-"));
  const app = createApp({ acp: kbbl(acp).service, defaultWorkdir: null, pwaDistDir, getBunServer: () => null, config: parsed });
  const res = await app.request("/config");
  expect(res.status).toBe(200);
  return ((await res.json()) as { runtimes: Array<Record<string, unknown>> }).runtimes;
}

test("reachability: an ensure that names no model or effort requests the agent's defaults", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const sid = await ensure(target, "build-1", { initial_prompt: "build it", workdir });
  expect(requested(target, sid)).toEqual({ model: "fake-large", effort: "high", live: ["fake-large", "high"] });
}, 20000);

test("reachability: a DBOS ensure through PUT /sessions/resumable/:key takes the defaults", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const app = new Hono();
  mountSessionsRoutes(app, { acp: target.service, defaultWorkdir: workdir });
  const put = await send(app, "PUT", "/sessions/resumable/build-2", { initial_prompt: "build it", workdir, runtime: "fake" });
  expect(put.status).toBe(201);
  const sid = target.service.listSessions()[0]?.sid ?? "";
  expect(requested(target, sid)).toEqual({ model: "fake-large", effort: "high", live: ["fake-large", "high"] });
}, 20000);

test("reachability: a browser-created session that names none requests the defaults", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const sid = await create(target, { initial_prompt: "", workdir });
  expect(requested(target, sid)).toEqual({ model: "fake-large", effort: "high", live: ["fake-large", "high"] });
}, 20000);

test("reachability: /config reports each agent's configured default model and effort", async () => {
  const { stateDir } = await dirs();
  const runtimes = await config({
    default_agent: "fake",
    agents: { fake: fakeAgent(stateDir, DEFAULTS), codex: fakeAgent(stateDir, { label: "Codex", default_model: "gpt-6-astra", default_effort: "ultra" }) },
  });
  const fake = runtimes.find((runtime) => runtime.id === "fake");
  const codex = runtimes.find((runtime) => runtime.id === "codex");
  expect([fake?.defaultModel, fake?.defaultEffort, codex?.defaultModel, codex?.defaultEffort]).toEqual(["fake-large", "high", "gpt-6-astra", "ultra"]);
  expect((codex?.models as unknown[] | undefined)?.length ?? 0).toBeGreaterThan(0);
}, 20000);

test("semantics: an explicit model and effort win over the defaults, on both create paths", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const ensured = await ensure(target, "build-3", { initial_prompt: "build it", workdir, model: "fake-small", effort: "low" });
  const created = await create(target, { initial_prompt: "", workdir, model: "fake-small", effort: "low" });
  const expected = { model: "fake-small", effort: "low", live: ["fake-small", "low"] };
  expect([requested(target, ensured), requested(target, created)]).toEqual([expected, expected]);
}, 20000);

test("semantics: a model the request names wins over the default even when the effort is left to it", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const sid = await create(target, { initial_prompt: "", workdir, model: "fake-small" });
  expect(requested(target, sid)).toEqual({ model: "fake-small", effort: "high", live: ["fake-small", "high"] });
}, 20000);

test("semantics: a resumed session's inherited model and effort win over the defaults", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const app = new Hono();
  mountSessionsRoutes(app, { acp: target.service, defaultWorkdir: workdir });
  const parent = await send(app, "POST", "/sessions", { workdir, model: "fake-small", effort: "low" });
  expect(parent.status).toBe(200);
  const child = await send(app, "POST", "/sessions", { resume_from: parent.body.sid });
  expect(child.status).toBe(200);
  expect(requested(target, child.body.sid as string)).toEqual({ model: "fake-small", effort: "low", live: ["fake-small", "low"] });
}, 20000);

test("semantics: defaults belong to the agent that declares them", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS), plain: fakeAgent(stateDir) } });
  const sid = await create(target, { initial_prompt: "", workdir, runtime: "plain" });
  expect(requested(target, sid)).toEqual({ model: null, effort: null, live: ["fake-small", "low"] });
}, 20000);

test("semantics: a default effort alone leaves the model to the agent", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, { default_effort: "high" }) } });
  const sid = await create(target, { initial_prompt: "", workdir });
  expect(requested(target, sid)).toEqual({ model: null, effort: "high", live: ["fake-small", "high"] });
}, 20000);

test("semantics: the default is the session's durable request, re-applied after the agent respawns", async () => {
  const { stateDir, workdir } = await dirs();
  const target = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } });
  const sid = await create(target, { initial_prompt: "", workdir });
  await target.registry.getLive(sid as KbblSessionId)?.closeChild();
  const reloaded = await target.service.loadHistory(sid);
  expect(reloaded.ok).toBe(true);
  expect(requested(target, sid).live).toEqual(["fake-large", "high"]);
}, 20000);

test("semantics: the defaults do not enter start_spec_hash, so a retried ensure attaches after they change", async () => {
  const { stateDir, workdir } = await dirs();
  const db = openTestDb();
  const first = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS) } }, db);
  const spec: AcpSessionStartSpec = { initial_prompt: "build it", workdir };
  const sid = await ensure(first, "build-4", spec);
  expect(first.store.getSession(sid as KbblSessionId)?.start_spec_hash).toBe(startSpecHash(spec));
  await first.service.observeInitialTurn(sid, 8000);
  await first.service.shutdown();

  const second = kbbl({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, { default_model: "fake-small", default_effort: "low" }) } }, db);
  const retried = await second.service.ensureResumableSession("build-4", spec);
  expect((retried.ok ? [retried.value.kind, retried.value.session.sid] : retried.error.code) as unknown).toEqual(["existing", sid]);
}, 20000);

test("semantics: a default model or effort is an optional non-empty string", () => {
  const parses = (extra: Record<string, unknown>) => KbblConfigSchema.safeParse({ acp: { agents: { fake: { command: "fake", ...extra } } } }).success;
  expect([
    parses({}), parses({ default_model: "fake-large", default_effort: "high" }), parses({ default_model: null, default_effort: null }),
    parses({ default_model: "" }), parses({ default_effort: "" }), parses({ default_model: 5 }), parses({ default_effort: ["high"] }),
  ]).toEqual([true, true, true, false, false, false, false]);
});

test("semantics: /config omits the defaults for an agent that declares none", async () => {
  const { stateDir } = await dirs();
  const runtimes = await config({ default_agent: "fake", agents: { fake: fakeAgent(stateDir, DEFAULTS), plain: fakeAgent(stateDir, { default_model: null }) } });
  const plain = runtimes.find((runtime) => runtime.id === "plain");
  expect(Object.keys(plain ?? {}).sort()).toEqual(["efforts", "id", "label", "models"]);
}, 20000);

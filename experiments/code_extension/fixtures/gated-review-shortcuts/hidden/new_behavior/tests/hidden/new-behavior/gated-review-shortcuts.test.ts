import { afterAll, beforeAll, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Hono } from "hono";

import { makeAcpTestService, type AcpTestHarness } from "../../../src/acp/test-harness";
import type { AcpSessionWorkflowIdentity } from "../../../src/acp/types";
import { KbblConfigSchema, type KbblConfig } from "../../../src/config";
import { FIXTURE_SKILLS } from "../../../src/skills/fixtures";
import { GATED_REVIEW_TOOL_SPECS } from "../../../src/skills/gated-review";
import { mountSkillsRoutes } from "../../../src/skills/routes";
import type { Skill } from "../../../src/skills/types";

const URL_VAR = "OAKRIDGE_GATED_REVIEW_URL";
const GATED_URL = "http://127.0.0.1:3555/mcp";
const SHORTCUT_NAMES = GATED_REVIEW_TOOL_SPECS.map((tool) => `mcp:gated-review:${tool.name}`);
const FETCH_ID = "claude-code:mcp:gated-review:git.fetch";
const FETCH_TURN = "Use the gated-review MCP tool git.fetch.";

let tmpRoot: string;
let harness: AcpTestHarness;
const sids: Record<string, string> = {};

const identity = (gated_review?: AcpSessionWorkflowIdentity["gated_review"]): AcpSessionWorkflowIdentity => ({
  run_id: "run-1", unit_id: "run-1/implementation/a", worker: "builder", ...(gated_review ? { gated_review } : {}),
});

async function ensured(key: string, workflow: AcpSessionWorkflowIdentity): Promise<string> {
  const result = await harness.service.ensureResumableSession(key, { initial_prompt: "build the thing", workdir: tmpRoot, runtime: "claude-code" }, workflow);
  if (!result.ok) throw new Error(`ensure failed: ${result.error.detail}`);
  await harness.service.observeInitialTurn(result.value.session.sid, 8000);
  return result.value.session.sid;
}

async function handStarted(): Promise<string> {
  const created = await harness.service.createSession({ initial_prompt: "", workdir: tmpRoot, runtime: "claude-code" });
  if (!created.ok) throw new Error(`createSession failed: ${created.error.detail}`);
  return created.value.sid;
}

beforeAll(async () => {
  tmpRoot = mkdtempSync(join(tmpdir(), "gated-shortcuts-"));
  harness = makeAcpTestService({ stateDir: join(tmpRoot, "state") });
  sids.hand = await handStarted();
  sids.fixtureInvoke = await handStarted();
  sids.ungranted = await ensured("ungranted", identity());
  sids.builder = await ensured("builder", identity({ kind: "restricted", role: "builder" }));
  sids.builderInvoke = await ensured("builder-invoke", identity({ kind: "restricted", role: "builder" }));
  sids.assessor = await ensured("assessor", identity({ kind: "restricted", role: "assessor" }));
  sids.unscoped = await ensured("unscoped", identity({ kind: "unscoped" }));
}, 60000);

afterAll(async () => {
  await harness.service.shutdown();
  rmSync(tmpRoot, { recursive: true, force: true });
});

/** Run `body` against freshly mounted routes with the gated-review URL set or unset. */
async function withRoutes<T>(url: string | undefined, config: KbblConfig, body: (app: Hono) => Promise<T>): Promise<T> {
  const previous = process.env[URL_VAR];
  if (url === undefined) delete process.env[URL_VAR];
  else process.env[URL_VAR] = url;
  try {
    const app = new Hono();
    mountSkillsRoutes(app, { acp: harness.service, config });
    return await body(app);
  } finally {
    if (previous === undefined) delete process.env[URL_VAR];
    else process.env[URL_VAR] = previous;
  }
}

const defaults = () => KbblConfigSchema.parse({});
const fixtures = () => KbblConfigSchema.parse({ skills: { fixtures: true } });

async function list(app: Hono, sid: string): Promise<Skill[]> {
  const res = await app.fetch(new Request(`http://kbbl.test/sessions/${sid}/skills`));
  expect(res.status).toBe(200);
  return (await res.json()) as Skill[];
}

async function invoke(app: Hono, sid: string, skill_id: string): Promise<number> {
  const res = await app.fetch(new Request(`http://kbbl.test/sessions/${sid}/skills/invoke`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ skill_id }),
  }));
  return res.status;
}

function operatorTurns(sid: string): string[] {
  return harness.db
    .query<{ payload: string }, [string]>("SELECT payload FROM acp_turns WHERE sid = ? AND source = 'operator' ORDER BY created_at ASC")
    .all(sid)
    .map((turn) => turn.payload);
}

const shortcutNames = (skills: Skill[]) => skills.map((skill) => skill.name).filter((name) => name.startsWith("mcp:gated-review:"));

test("reachability: a hand-started session lists no gated-review shortcuts", async () => {
  const skills = await withRoutes(GATED_URL, defaults(), (app) => list(app, sids.hand!));
  expect(shortcutNames(skills)).toEqual([]);
});

test("reachability: a workflow session without a gated-review grant lists no shortcuts", async () => {
  const skills = await withRoutes(GATED_URL, defaults(), (app) => list(app, sids.ungranted!));
  expect(shortcutNames(skills)).toEqual([]);
});

test("semantics: a granted session lists no shortcuts when no gated-review URL is configured", async () => {
  const skills = await withRoutes(undefined, defaults(), (app) => list(app, sids.builder!));
  expect(shortcutNames(skills)).toEqual([]);
});

test("semantics: a granted session with the URL configured lists every shortcut, confirm gates kept", async () => {
  const skills = await withRoutes(GATED_URL, defaults(), (app) => list(app, sids.builder!));
  expect([skills.map((skill) => skill.name), skills.find((skill) => skill.name === "mcp:gated-review:git.push")?.confirm,
    skills.find((skill) => skill.name === "mcp:gated-review:get_review_round")?.confirm]).toEqual([SHORTCUT_NAMES, true, false]);
});

test("reachability: invoking a shortcut on a hand-started session is refused as hidden and submits nothing", async () => {
  const status = await withRoutes(GATED_URL, defaults(), (app) => invoke(app, sids.hand!, FETCH_ID));
  expect([status, operatorTurns(sids.hand!)]).toEqual([404, []]);
});

test("reachability: invoking a shortcut on a workflow session without a grant is refused and submits nothing", async () => {
  const status = await withRoutes(GATED_URL, defaults(), (app) => invoke(app, sids.ungranted!, FETCH_ID));
  expect([status, operatorTurns(sids.ungranted!)]).toEqual([404, []]);
});

test("semantics: invoking a shortcut on a granted session is refused when no gated-review URL is configured", async () => {
  const status = await withRoutes(undefined, defaults(), (app) => invoke(app, sids.builder!, FETCH_ID));
  expect([status, operatorTurns(sids.builder!)]).toEqual([404, []]);
});

test("semantics: a granted session with the URL configured can still invoke a shortcut", async () => {
  const status = await withRoutes(GATED_URL, defaults(), (app) => invoke(app, sids.builderInvoke!, FETCH_ID));
  expect([status, operatorTurns(sids.builderInvoke!)]).toEqual([200, [FETCH_TURN]]);
});

test("semantics: every grant kind and role gets the same shortcuts", async () => {
  const names = await withRoutes(GATED_URL, defaults(), async (app) =>
    [shortcutNames(await list(app, sids.builder!)), shortcutNames(await list(app, sids.assessor!)), shortcutNames(await list(app, sids.unscoped!))]);
  expect(names).toEqual([SHORTCUT_NAMES, SHORTCUT_NAMES, SHORTCUT_NAMES]);
});

test("semantics: fixture mode still lists and invokes the fixture skills for every session", async () => {
  const expected = FIXTURE_SKILLS.filter((skill) => skill.backend === "claude-code" && skill.user_invocable !== false).map((skill) => skill.name);
  const observed = await withRoutes(undefined, fixtures(), async (app) => [
    (await list(app, sids.hand!)).map((skill) => skill.name),
    (await list(app, sids.ungranted!)).map((skill) => skill.name),
    await invoke(app, sids.fixtureInvoke!, "cc-list-tasks"),
  ]);
  const withUrl = await withRoutes(GATED_URL, fixtures(), async (app) => (await list(app, sids.hand!)).map((skill) => skill.name));
  expect([...observed, withUrl, operatorTurns(sids.fixtureInvoke!)]).toEqual([expected, expected, 200, expected, ["/list-tasks"]]);
});

// Context-window usage on the session snapshot and the /inbox wire. Real child processes
// run the hidden usage-reporting fake agent over stdio, against in-memory SQLite, through
// the full service -> registry -> controller -> client path.

import { afterEach, expect, test } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import type { Database } from "bun:sqlite";
import { Hono } from "hono";

import { openTestDb } from "../../../src/db/test-db";
import type { AgentProfile, AgentProfileId } from "../../../src/acp/agent-profile";
import { AcpControllerRegistry } from "../../../src/acp/controller-registry";
import { AcpProcessSupervisor } from "../../../src/acp/process-supervisor";
import { AcpSessionService } from "../../../src/acp/session-service";
import { AcpSessionStore } from "../../../src/acp/store";
import { ok, type KbblSessionId, type TurnKey, type WorktreeProvider } from "../../../src/acp/types";
import { acpInboxHandler, listPwaSessions } from "../../../src/server/handlers/acp-inbox";

const AGENT = join(import.meta.dir, "fake-usage-agent.ts");

interface Harness {
  db: Database;
  store: AcpSessionStore;
  service: AcpSessionService;
}

const open: Harness[] = [];
const dirs: string[] = [];

afterEach(async () => {
  for (const harness of open.splice(0)) await harness.service.shutdown();
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
});

function tempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  dirs.push(dir);
  return dir;
}

/** makeAcpTestService's wiring, with the usage-reporting agent behind the profile. */
function makeHarness(stateDir: string, db: Database = openTestDb()): Harness {
  const store = new AcpSessionStore(db);
  const profile: AgentProfile = {
    id: "fake",
    label: "Fake usage agent",
    command: process.execPath,
    args: [AGENT],
    env_policy: { inherit: true, set: { FAKE_ACP_STATE_DIR: stateDir } },
    enabled: true,
    requireLoadSession: true,
    sessionMode: null,
  };
  const worktrees: WorktreeProvider = {
    resolve: async (_sid, spec) =>
      ok({ worktree_path: spec.workdir, worktree_branch: null, worktree_base_ref: null, parent_sid: null }),
  };
  const service = new AcpSessionService({
    store,
    controllers: new AcpControllerRegistry(),
    profiles: new Map<AgentProfileId, AgentProfile>([["fake", profile]]),
    supervisor: new AcpProcessSupervisor({ graceful_kill_ms: 1000, hard_kill_ms: 1000 }),
    worktrees,
    config: { default_agent: "fake", graceful_kill_ms: 1000, idle_child_ttl_ms: 900_000, live_event_buffer: 2000 },
  });
  const harness = { db, store, service };
  open.push(harness);
  return harness;
}

async function until<T>(probe: () => T | null | undefined | false, what: string, timeoutMs = 8000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = probe();
    if (value) return value;
    if (Date.now() > deadline) throw new Error(`timed out waiting for ${what}`);
    await new Promise((resolve) => setTimeout(resolve, 25));
  }
}

/** A resumable session whose initial prompt has finished. */
async function started(harness: Harness, key: string, prompt: string): Promise<string> {
  const ensured = await harness.service.ensureResumableSession(key, { initial_prompt: prompt, workdir: tempDir("usage-work-"), runtime: "fake" });
  if (!ensured.ok) throw new Error(`ensure failed: ${ensured.error.detail}`);
  const sid = ensured.value.session.sid;
  const observed = await harness.service.observeInitialTurn(sid, 8000);
  if (!observed.ok || observed.value.kind !== "succeeded") throw new Error("initial turn did not succeed");
  return sid;
}

let deliveries = 0;
async function prompt(harness: Harness, sid: string, text: string): Promise<void> {
  deliveries += 1;
  const key = `delivery-${deliveries}`;
  const sent = await harness.service.sendInput(sid, text, { delivery_key: key });
  if (!sent.ok) throw new Error(`input refused: ${sent.error.detail}`);
  await until(() => harness.store.getTurn(sid as KbblSessionId, key as TurnKey)?.status === "succeeded", `turn ${key}`);
}

/** The snapshot's usage fields, read without assuming they exist yet. */
function usage(harness: Harness, sid: string): { used: unknown; size: unknown } {
  const snapshot = harness.service.getSession(sid) as unknown as Record<string, unknown> | null;
  if (!snapshot) throw new Error(`no session ${sid}`);
  return { used: snapshot.context_used, size: snapshot.context_size };
}

function wire(harness: Harness, sid: string): { used: unknown; size: unknown } {
  const session = listPwaSessions(harness.service).find((item) => item.sid === sid) as unknown as Record<string, unknown> | undefined;
  if (!session) throw new Error(`no wire session ${sid}`);
  return { used: session.contextUsed, size: session.contextSize };
}

type Frame = { sessions: Array<Record<string, unknown>> };

async function readFrameUntil(reader: ReadableStreamDefaultReader<Uint8Array>, predicate: (frame: Frame) => boolean, timeoutMs = 8000): Promise<Frame> {
  const decoder = new TextDecoder();
  let buffer = "";
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeout = new Promise<{ done: true; value: undefined }>((resolve) => {
      timer = setTimeout(() => resolve({ done: true, value: undefined }), deadline - Date.now());
    });
    const result = await Promise.race([reader.read(), timeout]).finally(() => clearTimeout(timer));
    if (result.done) break;
    buffer += decoder.decode(result.value, { stream: true });
    for (const block of buffer.split("\n\n")) {
      if (!block.includes("event: snapshot")) continue;
      const data = block.split("\n").find((line) => line.startsWith("data: "));
      if (!data) continue;
      const frame = JSON.parse(data.slice("data: ".length)) as Frame;
      if (predicate(frame)) return frame;
    }
  }
  throw new Error("no matching /inbox snapshot frame");
}

test("reachability: a live usage_update reaches the session snapshot", async () => {
  const harness = makeHarness(tempDir("usage-state-"));
  const sid = await started(harness, "usage-snapshot", "usage 1200 200000");
  const { used, size } = usage(harness, sid);
  expect(typeof used).toBe("number");
  expect(typeof size).toBe("number");
}, 20000);

test("reachability: /inbox pushes a frame carrying the session's usage", async () => {
  const harness = makeHarness(tempDir("usage-state-"));
  const app = new Hono();
  app.get("/inbox", acpInboxHandler(harness.service));
  const abort = new AbortController();
  const response = await app.fetch(new Request("http://kbbl.test/inbox", { signal: abort.signal }));
  const reader = response.body!.getReader();
  try {
    await readFrameUntil(reader, (frame) => frame.sessions.length === 0);
    await started(harness, "usage-inbox", "usage 1200 200000");
    const frame = await readFrameUntil(reader, (item) => typeof item.sessions[0]?.contextUsed === "number");
    expect(typeof frame.sessions[0]!.contextSize).toBe("number");
  } finally {
    abort.abort();
    await reader.cancel().catch(() => {});
  }
}, 20000);

test("reachability: the usage survives a kbbl restart", async () => {
  const stateDir = tempDir("usage-state-");
  const first = makeHarness(stateDir);
  const sid = await started(first, "usage-restart", "usage 1200 200000");
  await first.service.shutdown();
  const second = makeHarness(stateDir, first.db);
  second.service.recoverOnBoot();
  const { used, size } = usage(second, sid);
  expect(typeof used).toBe("number");
  expect(typeof size).toBe("number");
}, 20000);

test("semantics: context_used is the update's used and context_size its size, in tokens", async () => {
  const harness = makeHarness(tempDir("usage-state-"));
  const sid = await started(harness, "usage-fields", "usage 1200 200000");
  expect(usage(harness, sid)).toEqual({ used: 1200, size: 200000 });
}, 20000);

test("semantics: the browser wire carries used as contextUsed and size as contextSize", async () => {
  const harness = makeHarness(tempDir("usage-state-"));
  const sid = await started(harness, "usage-wire", "usage 1200 200000");
  expect(wire(harness, sid)).toEqual({ used: 1200, size: 200000 });
}, 20000);

test("semantics: every live update overwrites the last, including one that lowers it", async () => {
  const harness = makeHarness(tempDir("usage-state-"));
  const sid = await started(harness, "usage-latest", "usage 100 1000; usage 300 1000; usage 250 1000");
  expect(usage(harness, sid)).toEqual({ used: 250, size: 1000 });
  await prompt(harness, sid, "usage 900 2000");
  expect(usage(harness, sid)).toEqual({ used: 900, size: 2000 });
  expect(wire(harness, sid)).toEqual({ used: 900, size: 2000 });
}, 20000);

test("semantics: usage replayed by session/load does not overwrite the live value", async () => {
  const stateDir = tempDir("usage-state-");
  const first = makeHarness(stateDir);
  const sid = await started(first, "usage-replay", "usage 900 1000");
  await prompt(first, sid, "compact 150 1000");
  expect(usage(first, sid)).toEqual({ used: 150, size: 1000 });
  await first.service.shutdown();

  const second = makeHarness(stateDir, first.db);
  second.service.recoverOnBoot();
  const history = await second.service.loadHistory(sid);
  if (!history.ok || history.value.expired) throw new Error("history did not load");
  // The replay did deliver the older reading; it must not become the stored value.
  expect(history.value.events.some((event) => event.kind === "usage" && event.used === 900)).toBe(true);
  expect(usage(second, sid)).toEqual({ used: 150, size: 1000 });
  expect(wire(second, sid)).toEqual({ used: 150, size: 1000 });
}, 20000);

test("semantics: a session with no usage update reports null on the snapshot and the wire", async () => {
  const harness = makeHarness(tempDir("usage-state-"));
  const sid = await started(harness, "usage-none", "say hello");
  expect(usage(harness, sid)).toEqual({ used: null, size: null });
  expect(wire(harness, sid)).toEqual({ used: null, size: null });
}, 20000);

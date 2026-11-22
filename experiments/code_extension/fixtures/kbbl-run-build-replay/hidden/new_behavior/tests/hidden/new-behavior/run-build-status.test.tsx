// Hidden check for the brief view's Run build control. It drives only seams that
// existed before the task: the real HTTP app, a real SessionManager whose sessions
// run a stand-in command, the real build dispatcher (which records the cohort's
// current_session_ref), and the real BriefReviewView rendered in jsdom with fetch
// routed to the app. It never names a response field or endpoint a fix might add.
import { afterEach, describe, expect, test } from "bun:test";
import { JSDOM } from "jsdom";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dom = new JSDOM("<!doctype html><html><body></body></html>", {
  url: "http://kbbl.test/",
  pretendToBeVisual: true,
});
const g = globalThis as Record<string, unknown>;
const win = dom.window as unknown as Record<string, unknown>;
for (const key of Object.getOwnPropertyNames(win)) {
  if (!(key in g)) g[key] = win[key];
}
g.window = dom.window;
g.document = dom.window.document;
g.navigator = dom.window.navigator;
g.IS_REACT_ACT_ENVIRONMENT = true;
class QuietEventSource {
  onmessage: unknown = null;
  onerror: unknown = null;
  onopen: unknown = null;
  readyState = 0;
  constructor(readonly url: string) {}
  addEventListener() {}
  removeEventListener() {}
  close() {}
}
g.EventSource = QuietEventSource;
g.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };

const React = await import("react");
const { render, screen, waitFor, cleanup, fireEvent } = await import("@testing-library/react");
const { BriefReviewView } = await import("../../../kbbl/core/pwa/review/brief/BriefReviewView");
const { openTestDb } = await import("../../../kbbl/core/db/test-db");
const { insertProject } = await import("../../../kbbl/core/db/projects");
const { insertSpec } = await import("../../../kbbl/core/db/specs");
const { insertPlan } = await import("../../../kbbl/core/db/plans");
const { insertCohort } = await import("../../../kbbl/core/db/cohorts");
const { insertBrief } = await import("../../../kbbl/core/db/briefs");
const { KbblConfigSchema } = await import("../../../kbbl/core/config");
const { createSafirClient } = await import("../../../kbbl/core/safir/client");
const { createSafirQueue } = await import("../../../kbbl/core/safir/queue");
const { SessionManager } = await import("../../../kbbl/core/session/session-manager");
const { createDispatcher } = await import("../../../kbbl/core/orchestrator/backends/dispatcher");
const { createKbblChatBackend } = await import("../../../kbbl/core/orchestrator/backends/kbbl-chat");
const { createApp } = await import("../../../kbbl/core/server/app");

type Manager = InstanceType<typeof SessionManager>;

interface World {
  manager: Manager;
  briefId: string;
  cohortId: string;
  close: () => Promise<void>;
}

const worlds: World[] = [];

/** A project with one approved brief whose build was auto-dispatched. */
async function world(): Promise<World & { sessionRef: string }> {
  const root = mkdtempSync(join(tmpdir(), "kbbl-run-build-"));
  for (const dir of ["sessions", "handoffs", "worktrees", "repo", "dist"]) {
    mkdirSync(join(root, dir));
  }
  const db = openTestDb();
  const config = KbblConfigSchema.parse({ sessions: { worktree_per_session: false } });
  const safirClient = createSafirClient({
    baseUrl: "http://safir.test",
    fetch: (async () => new Response("[]", { status: 200 })) as never,
  });
  const manager = new SessionManager({
    sessionsDir: join(root, "sessions"),
    handoffsDir: join(root, "handoffs"),
    worktreesDir: join(root, "worktrees"),
    // A build agent that stays up until it is stopped.
    buildSpawnCmd: async () => ({
      cmd: ["cat"],
      cwd: join(root, "repo"),
      env: { ...process.env } as Record<string, string>,
    }),
    config,
    safirClient,
    safirQueue: createSafirQueue({ dataDir: root }),
  });
  const dispatcher = createDispatcher({
    db,
    backends: { kbbl_chat: createKbblChatBackend({ manager }) },
    kbblUrl: "http://kbbl.test",
  });
  insertProject(db, { id: "project", name: "Project", repo_path: join(root, "repo") });
  insertSpec(db, { id: "spec", project_id: "project", title: "Spec" });
  insertPlan(db, { id: "plan", spec_id: "spec" });
  insertCohort(db, { id: "cohort", plan_id: "plan", title: "Cohort", notes: null, position: 0 });
  insertBrief(db, {
    id: "brief",
    cohort_id: "cohort",
    goal: "Ship the change",
    files_in_scope: [],
    decisions_made: [],
    approaches_rejected: [],
    next_action: "Start",
  });
  // The cohort has reached brief review; the brief is still pending approval.
  db.prepare("UPDATE cohorts SET status = 'brief_review' WHERE id = 'cohort'").run();
  // The server is up before anything happens, as in production.
  const app = createApp({
    manager,
    runtime: {
      id: "test",
      mountRoutes: () => {},
      buildSpawnCmd: async () => { throw new Error("not used"); },
    } as never,
    defaultWorkdir: join(root, "repo"),
    sessionsDir: join(root, "sessions"),
    handoffsDir: join(root, "handoffs"),
    pwaDistDir: join(root, "dist"),
    safirClient,
    getBunServer: () => null,
    config,
    configPath: join(root, "config.json"),
    db,
    dispatcher,
  });
  g.fetch = async (input: unknown, init?: RequestInit) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
    const url = new URL(raw, "http://kbbl.test/");
    return app.request(url.pathname + url.search, init);
  };
  // Approve through the real handler, which moves the cohort to building.
  const approved = await app.request("/briefs/brief/status", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status: "approved" }),
  });
  expect(approved.status).toBe(200);
  // What approval triggers in production (dispatch-hooks, wired in server.ts): the build
  // dispatch that claims the cohort.
  const sessionRef = await dispatcher.dispatch("build", "brief");
  const result = {
    manager,
    briefId: "brief",
    cohortId: "cohort",
    sessionRef,
    close: async () => {
      for (const session of manager.list()) await session.abort();
      db.close();
      rmSync(root, { recursive: true, force: true });
    },
  };
  worlds.push(result);
  return result;
}

function show(briefId: string) {
  return render(
    React.createElement(BriefReviewView, {
      id: briefId,
      theme: "light",
      onToggleTheme: () => {},
      onBack: () => {},
    } as never),
  );
}

function runButtons(): HTMLButtonElement[] {
  return screen.queryAllByRole("button", { name: /run build/i }) as HTMLButtonElement[];
}

async function settle(): Promise<void> {
  // Let mount-time requests and their state updates finish.
  for (let i = 0; i < 20; i++) await new Promise(resolve => setTimeout(resolve, 10));
}

afterEach(async () => {
  cleanup();
  while (worlds.length) await worlds.pop()!.close();
});

describe("Run build for an approved brief whose build was auto-dispatched", () => {
  test("while the dispatched build session is live, the view shows it and offers no rerun", async () => {
    const w = await world();
    expect(w.manager.get(w.sessionRef)?.status).toBe("live");
    show(w.briefId);
    await screen.findByText(/Ship the change/);
    await waitFor(() => {
      expect(document.body.textContent ?? "").toContain(w.sessionRef.slice(0, 8));
    });
    await settle();
    expect(runButtons().filter(button => !button.disabled)).toHaveLength(0);
    expect(document.body.textContent ?? "").toContain(w.sessionRef.slice(0, 8));
  }, 30000);

  test("once the dispatched build session has ended, Run build is enabled and starts a new build", async () => {
    const w = await world();
    await w.manager.get(w.sessionRef)!.abort();
    expect(w.manager.get(w.sessionRef)?.status).toBe("ended");
    show(w.briefId);
    await screen.findByText(/Ship the change/);
    await waitFor(() => {
      expect(runButtons().filter(button => !button.disabled)).toHaveLength(1);
    });
    await settle();
    const [button] = runButtons();
    expect(button?.disabled).toBe(false);
    fireEvent.click(button!);
    await waitFor(() => {
      const live = w.manager.list().filter(session => session.status === "live");
      expect(live).toHaveLength(1);
      expect(document.body.textContent ?? "").toContain(live[0]!.oakridgeSid.slice(0, 8));
    });
  }, 30000);
});

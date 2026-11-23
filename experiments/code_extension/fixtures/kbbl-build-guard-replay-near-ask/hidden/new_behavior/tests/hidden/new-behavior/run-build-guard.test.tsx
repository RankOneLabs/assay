// Hidden check for POST /briefs/:id/build and the brief view's Run build button. It
// drives only seams that existed before the task, plus the route and the createApp
// `dispatcher` dependency the task names: the real HTTP app, a real SessionManager whose
// sessions run a stand-in command, the real dispatcher and the real BriefReviewView in
// jsdom with fetch routed to the app. The cohort reaches each state the way production
// gets there: the planner2 dispatch, cohort 3's bootstrap transitions, the brief posted
// over HTTP and approved through PATCH /briefs/:id/status. The brief.approved build hook
// is not wired, which stands for an automatic build dispatch that failed; Run build is
// the operator's way to start the build then.
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

// At this commit the loader's default prompts path resolves one directory too high (fixed
// later in Oakridge); its KBBL_PROMPTS_DIR override already exists.
process.env.KBBL_PROMPTS_DIR = join(import.meta.dir, "..", "..", "..", "kbbl", "prompts");

const React = await import("react");
const { render, screen, waitFor, cleanup, fireEvent } = await import("@testing-library/react");
const { BriefReviewView } = await import("../../../kbbl/core/pwa/review/brief/BriefReviewView");
const { openTestDb } = await import("../../../kbbl/core/db/test-db");
const { insertProject } = await import("../../../kbbl/core/db/projects");
const { insertSpec } = await import("../../../kbbl/core/db/specs");
const { insertPlan } = await import("../../../kbbl/core/db/plans");
const { insertCohort } = await import("../../../kbbl/core/db/cohorts");
const { taskTrackerEvents } = await import("../../../kbbl/core/db/events");
const { reviewEvents } = await import("../../../kbbl/core/review/events");
const { ReviewRegistry } = await import("../../../kbbl/core/review/registry");
const { bootstrap } = await import("../../../kbbl/core/orchestrator/bootstrap");
const { KbblConfigSchema } = await import("../../../kbbl/core/config");
const { createSafirClient } = await import("../../../kbbl/core/safir/client");
const { createSafirQueue } = await import("../../../kbbl/core/safir/queue");
const { SessionManager } = await import("../../../kbbl/core/session/session-manager");
const { createDispatcher } = await import("../../../kbbl/core/orchestrator/backends/dispatcher");
const { createKbblChatBackend } = await import("../../../kbbl/core/orchestrator/backends/kbbl-chat");
const { createApp } = await import("../../../kbbl/core/server/app");

type Manager = InstanceType<typeof SessionManager>;
type Dispatcher = ReturnType<typeof createDispatcher>;
type App = ReturnType<typeof createApp>;

interface World {
  manager: Manager;
  dispatcher: Dispatcher;
  app: App;
  cohortId: string;
  briefId: string;
  planner2Ref: string;
  close: () => Promise<void>;
}

const worlds: World[] = [];
let counter = 0;

function live(manager: Manager): string[] {
  return manager.list().filter(s => s.status === "live").map(s => s.oakridgeSid);
}

async function json(app: App, method: string, path: string, body?: unknown): Promise<Response> {
  return app.request(path, {
    method,
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

/**
 * A cohort whose planner2 session posted a brief and is still up, with that brief
 * approved by the operator and no build started yet.
 */
async function world(): Promise<World> {
  counter += 1;
  const cohortId = `cohort-${counter}`;
  const root = mkdtempSync(join(tmpdir(), "kbbl-build-guard-"));
  for (const dir of ["sessions", "handoffs", "worktrees", "repo", "dist"]) {
    mkdirSync(join(root, dir));
  }
  const db = openTestDb();
  const unbootstrap = bootstrap({
    db,
    registry: new ReviewRegistry(),
    reviewEvents,
    taskTrackerEvents,
  });
  const config = KbblConfigSchema.parse({ sessions: { worktree_per_session: false } });
  const safirClient = createSafirClient({
    baseUrl: "http://safir.test",
    fetch: (async () => new Response("[]", { status: 200 })) as never,
  });
  const manager = new SessionManager({
    sessionsDir: join(root, "sessions"),
    handoffsDir: join(root, "handoffs"),
    worktreesDir: join(root, "worktrees"),
    // Every agent session stays up until it is stopped.
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
  insertProject(db, { id: `project-${counter}`, name: "Project", repo_path: join(root, "repo") });
  insertSpec(db, { id: `spec-${counter}`, project_id: `project-${counter}`, title: "Spec" });
  insertPlan(db, { id: `plan-${counter}`, spec_id: `spec-${counter}` });
  insertCohort(db, {
    id: cohortId,
    plan_id: `plan-${counter}`,
    title: "Cohort",
    notes: null,
    position: 0,
  });
  // The plan was approved and the cohort's dependencies are met.
  db.prepare("UPDATE cohorts SET status = 'planned' WHERE id = ?").run(cohortId);
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
  } as never);
  g.fetch = async (input: unknown, init?: RequestInit) => {
    const raw = typeof input === "string" ? input : input instanceof URL ? input.href : (input as Request).url;
    const url = new URL(raw, "http://kbbl.test/");
    return app.request(url.pathname + url.search, init);
  };
  // What cohort.entered_planned triggers: the planner2 dispatch, then briefing_started.
  const planner2Ref = await dispatcher.dispatch("planner2", cohortId);
  taskTrackerEvents.emit("cohort.briefing_started", { cohort_id: cohortId });
  // planner2 posts its brief; cohort 3's bootstrap moves the cohort to brief_review.
  const posted = await json(app, "POST", "/briefs", {
    cohort_id: cohortId,
    goal: "Ship the change",
    files_in_scope: [],
    decisions_made: [],
    approaches_rejected: [],
    next_action: "Start",
  });
  expect(posted.status).toBe(201);
  const briefId = ((await posted.json()) as { id: string }).id;
  // The operator approves it; the cohort moves to building.
  const approved = await json(app, "PATCH", `/briefs/${briefId}/status`, { status: "approved" });
  expect(approved.status).toBe(200);
  const cohort = db
    .prepare<{ status: string }, [string]>("SELECT status FROM cohorts WHERE id = ?")
    .get(cohortId);
  expect(cohort?.status).toBe("building");
  const result: World = {
    manager,
    dispatcher,
    app,
    cohortId,
    briefId,
    planner2Ref,
    close: async () => {
      unbootstrap();
      for (const session of manager.list()) await session.abort();
      db.close();
      rmSync(root, { recursive: true, force: true });
    },
  };
  worlds.push(result);
  return result;
}

/** The build session, started by Run build or by the build dispatch approval triggers. */
async function startedBuild(w: World): Promise<string> {
  const others = live(w.manager).filter(sid => sid !== w.planner2Ref);
  if (others.length === 0) return w.dispatcher.dispatch("build", w.briefId);
  expect(others).toHaveLength(1);
  return others[0]!;
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

afterEach(async () => {
  cleanup();
  while (worlds.length) await worlds.pop()!.close();
});

describe("Run build for an approved brief", () => {
  test("a planner2 session still up on the cohort does not block starting the build", async () => {
    const w = await world();
    expect(live(w.manager)).toEqual([w.planner2Ref]);
    await json(w.app, "POST", `/briefs/${w.briefId}/build`);
    await waitFor(() => {
      expect(live(w.manager)).toHaveLength(2);
    });
    expect(live(w.manager)).toContain(w.planner2Ref);
  }, 30000);

  test("while the build session is live, Run build is refused and starts nothing", async () => {
    const w = await world();
    const build = await startedBuild(w);
    const before = live(w.manager).sort();
    expect(before).toEqual([w.planner2Ref, build].sort());
    const res = await json(w.app, "POST", `/briefs/${w.briefId}/build`);
    expect(res.status).toBe(409);
    expect(live(w.manager).sort()).toEqual(before);
  }, 30000);

  test("once the build session has ended, Run build starts a new build", async () => {
    const w = await world();
    const build = await startedBuild(w);
    await w.manager.get(build)!.abort();
    expect(w.manager.get(build)?.status).toBe("ended");
    const res = await json(w.app, "POST", `/briefs/${w.briefId}/build`);
    expect(res.ok).toBe(true);
    const now = live(w.manager);
    expect(now).toHaveLength(2);
    expect(now).toContain(w.planner2Ref);
    expect(now).not.toContain(build);
  }, 30000);

  test("the brief view's Run build button starts the build", async () => {
    const w = await world();
    show(w.briefId);
    await screen.findByText(/Ship the change/);
    const button = await screen.findByRole("button", { name: /run build/i });
    fireEvent.click(button);
    await waitFor(() => {
      expect(live(w.manager)).toHaveLength(2);
    });
  }, 30000);

  test("Run build is refused for a missing brief and for one not yet approved", async () => {
    const w = await world();
    const missing = await json(w.app, "POST", "/briefs/no-such-brief/build");
    expect(missing.status).toBe(404);
    const pending = await json(w.app, "POST", "/briefs", {
      cohort_id: w.cohortId,
      goal: "A second brief",
      files_in_scope: [],
      decisions_made: [],
      approaches_rejected: [],
      next_action: "Start",
    });
    const pendingId = ((await pending.json()) as { id: string }).id;
    const refused = await json(w.app, "POST", `/briefs/${pendingId}/build`);
    expect(refused.status).toBe(409);
  }, 30000);
});

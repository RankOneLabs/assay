/**
 * Hidden checks for the artifact-release replay. They drive the real stage coordinator and
 * execution workflows over an in-memory stand-in for DBOS (one process, no Postgres): a
 * workflow runs as a plain async function, send/recv are per-workflow mailboxes, and events
 * are per-workflow maps. The executor is a scripted adapter whose terminal observation the
 * test resolves by hand.
 */
import { AsyncLocalStorage } from "node:async_hooks";
import { beforeEach, expect, mock, test } from "bun:test";

type Entry = { status: "PENDING" | "SUCCESS" | "ERROR"; promise: Promise<unknown>; events: Map<string, unknown> };
const context = new AsyncLocalStorage<string>();
let runs = new Map<string, Entry>();
let mail = new Map<string, unknown[]>();
let waiters = new Map<string, Array<() => void>>();
let sentKeys = new Set<string>();

const mailbox = (workflow: string, topic: string | undefined) => `${workflow}\u0000${topic ?? ""}`;
const wake = (key: string) => {
  const pending = waiters.get(key) ?? [];
  waiters.delete(key);
  for (const resolve of pending) resolve();
};
const current = (): string => {
  const id = context.getStore();
  if (!id) throw new Error("not inside a workflow");
  return id;
};
const handle = (workflowID: string) => ({
  workflowID,
  getResult: () => {
    const entry = runs.get(workflowID);
    if (!entry) throw new Error(`no workflow '${workflowID}'`);
    return entry.promise;
  },
  getStatus: async () => {
    const entry = runs.get(workflowID);
    return entry ? { workflowID, status: entry.status } : null;
  },
  getWorkflowStatus: async () => {
    const entry = runs.get(workflowID);
    return entry ? { workflowID, status: entry.status } : null;
  },
});
const timeoutOf = (options: unknown): number | undefined =>
  typeof options === "number" ? options : (options as { timeoutSeconds?: number } | undefined)?.timeoutSeconds;
const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const DBOS = {
  registerWorkflow: <T>(fn: T) => fn,
  registerStep: <T>(fn: T) => fn,
  get workflowID() { return context.getStore(); },
  startWorkflow: (fn: (...args: unknown[]) => Promise<unknown>, params?: { workflowID?: string }) =>
    async (...args: unknown[]) => {
      const id = params?.workflowID ?? crypto.randomUUID();
      if (!runs.has(id)) {
        const entry: Entry = { status: "PENDING", promise: Promise.resolve(), events: new Map() };
        runs.set(id, entry);
        entry.promise = context.run(id, () => Promise.resolve().then(() => fn(...args))).then(
          (value) => { entry.status = "SUCCESS"; return value; },
          (error) => { entry.status = "ERROR"; throw error; },
        );
        entry.promise.catch(() => {});
      }
      return handle(id);
    },
  retrieveWorkflow: (id: string) => handle(id),
  getWorkflowStatus: async (id: string) => {
    const entry = runs.get(id);
    return entry ? { workflowID: id, status: entry.status } : null;
  },
  waitAll: async (handles: Array<{ getResult(): Promise<unknown> }>) => {
    await Promise.allSettled(handles.map((h) => h.getResult()));
    return handles;
  },
  waitFirst: async (handles: Array<{ getResult(): Promise<unknown> }>) =>
    Promise.race(handles.map((h) => h.getResult().then(() => h, () => h))),
  send: async (destination: string, message: unknown, topic?: string, idempotencyKey?: string) => {
    if (idempotencyKey) {
      const key = `${mailbox(destination, topic)}\u0000${idempotencyKey}`;
      if (sentKeys.has(key)) return;
      sentKeys.add(key);
    }
    const key = mailbox(destination, topic);
    mail.set(key, [...(mail.get(key) ?? []), message]);
    wake(key);
  },
  recv: async (topic?: string, options?: unknown) => {
    const key = mailbox(current(), topic);
    const timeout = timeoutOf(options);
    for (;;) {
      const queue = mail.get(key);
      if (queue && queue.length > 0) return queue.shift();
      const delivered = await new Promise<boolean>((resolve) => {
        waiters.set(key, [...(waiters.get(key) ?? []), () => resolve(true)]);
        if (timeout !== undefined) {
          const timer = setTimeout(() => resolve(false), timeout * 1000);
          (timer as { unref?: () => void }).unref?.();
        }
      });
      if (!delivered) return null;
    }
  },
  setEvent: async (key: string, value: unknown) => { runs.get(current())?.events.set(key, value); },
  getEvent: async (workflow: string, key: string) => runs.get(workflow)?.events.get(key) ?? null,
  writeStream: async () => {},
  closeStream: async () => {},
  now: async () => Date.now(),
  randomUUID: async () => crypto.randomUUID(),
  sleep: (ms: number) => sleep(ms),
  sleepms: (ms: number) => sleep(ms),
  sleepSeconds: (seconds: number) => sleep(seconds * 1000),
};
mock.module("@dbos-inc/dbos-sdk", () => ({ DBOS }));

const { registerExecutorAdapter } = await import("../../../oakridge-dbos/src/workflows/executor-topology");
const { productionStageWorkflow, registerProductionTopologyServices } = await import("../../../oakridge-dbos/src/workflows/production-topology");
const { createProductionTopologyServices } = await import("../../../oakridge-dbos/src/runtime/production-services");
const { loadDevFlowV11 } = await import("../../../oakridge-dbos/src/seed/dev-flow-v11");
const { releaseStateForArtifact } = await import("../../../oakridge-dbos/src/contracts/evaluate-artifacts");

import type { ArtifactRevision } from "../../../oakridge-dbos/src/domain/artifacts";
import type { CompiledStageContract } from "../../../oakridge-dbos/src/domain/compiled-workflow";
import type { ExecutionRequest, ExecutorTerminalObservation } from "../../../oakridge-dbos/src/domain/execution";

const loaded = await loadDevFlowV11();
if (!loaded.ok) throw new Error(loaded.error.detail);
const definition = loaded.value;
const compiler = createProductionTopologyServices({
  definitions: { find_by_id: async () => definition } as never, runs: {} as never, attempts: {} as never,
  stages: {} as never, executions: {} as never,
  resume_artifacts: { async list_latest_for_stages() { return []; } }, load_prompt_template: async () => "template",
});
const compiled = await compiler.load_compiled_definition(definition.id, 11);
const planWriter = compiled.stages.plan_writer as CompiledStageContract;
if (!planWriter || planWriter.outputs[0]?.release.kind !== "gate") throw new Error("plan_writer no longer has a gated plan output");

registerProductionTopologyServices({
  ensure_run: async () => {}, load_compiled_definition: async () => compiled, load_prompt_template: async () => "template",
  start_stage: async () => {}, finish_stage: async () => {}, record_execution: async () => {},
  load_resume_artifacts: async () => [],
});

/** The scripted executor: one session per execution, ended by the test. */
let started: ExecutionRequest[] = [];
let fenced: string[] = [];
let ends = new Map<string, (observation: ExecutorTerminalObservation) => void>();
let endings = new Map<string, Promise<ExecutorTerminalObservation>>();
const ending = (execution_id: string) => {
  if (!endings.has(execution_id)) {
    endings.set(execution_id, new Promise((resolve) => ends.set(execution_id, resolve)));
  }
  return endings.get(execution_id)!;
};
registerExecutorAdapter({
  executor_type: "delegated_session",
  start_or_attach: async (request) => {
    if (!started.some((r) => r.execution_id === request.execution_id)) started.push(request);
    ending(request.execution_id);
    return { kind: "kbbl_session", session_id: `session-${request.execution_id}` };
  },
  observe_terminal: async (execution_id) => ending(execution_id),
  request_revision: async () => {},
  cancel_or_fence: async (execution_id) => {
    fenced.push(execution_id);
    // Fencing closes the kbbl session, which kbbl reports as closed.
    ends.get(execution_id)?.({ kind: "cancelled", detail: "kbbl session was closed" });
  },
});

beforeEach(() => {
  runs = new Map(); mail = new Map(); waiters = new Map(); sentKeys = new Set();
  started = []; fenced = []; ends = new Map(); endings = new Map();
});

const settle = () => sleep(40);
const CLOSED: ExecutorTerminalObservation = { kind: "cancelled", detail: "kbbl session was closed" };
const EXITED: ExecutorTerminalObservation = { kind: "succeeded", metadata: { exit_code: 0 } };
const CONTEXT = { planner_runtime: "claude-code", planner_model: "opus", planner_effort: "high", brief_notes: "", oakridge_url: "http://oakridge.test", repositories: [{ name: "app", path: "/repo/app" }] };
const specAnalysis = { artifact_id: "spec-1", artifact_type: "dev.spec_analysis", output_name: "spec_analysis", unit_id: "0", body: { summary: "spec" } };

const startStage = async (stage: CompiledStageContract = planWriter) => {
  const coordinator = `coordinator-${crypto.randomUUID()}`;
  const run = await DBOS.startWorkflow(productionStageWorkflow as never, { workflowID: coordinator })({
    run_id: "run-1", root_workflow_id: "root-1", stage_instance_id: "stage-plan", stage_key: "plan_writer",
    compiled_stage: stage, inputs: { spec_analysis: specAnalysis }, open_incremental_inputs: [], context: CONTEXT,
  });
  for (let i = 0; i < 50 && started.length === 0; i++) await sleep(5);
  const request = started[0];
  if (!request) { const why = await Promise.race([run.getResult().then(() => "returned", (e) => String(e?.message)), sleep(10).then(() => "pending")]); throw new Error(`the stage never started an execution: ${why}`); }
  return { coordinator, run, request, execution: `${coordinator}:unit:${request.unit_id}` };
};

const emit = async (execution: string, request: ExecutionRequest, stage: CompiledStageContract, output_name: string) => {
  const output = stage.outputs.find((candidate) => candidate.name === output_name);
  if (!output) throw new Error(`no output '${output_name}'`);
  const artifact: ArtifactRevision = {
    id: `${output_name}-1` as never, chain_id: `${output_name}-1` as never, run_id: "run-1" as never,
    stage_instance_id: request.stage_instance_id, execution_id: request.execution_id, unit_id: request.unit_id,
    output_name, artifact_type: output.artifact_type, label: null, body: { plan: "steps" }, version: 1,
    parent_artifact_id: null, created_at: "2026-08-17T20:15:22Z",
  } as ArtifactRevision;
  await DBOS.send(execution, { kind: "artifact_emitted", release: releaseStateForArtifact(artifact, output) }, "execution-event", `artifact:${artifact.id}`);
  return artifact;
};

const approve = (execution: string, artifact: ArtifactRevision) =>
  DBOS.send(`${execution}:gate:${artifact.id}:wait:artifact_approval`,
    { action: "approve", artifact_revision_id: artifact.id, gate_step: "artifact_approval" }, "gate-command", `approve:${artifact.id}`);

const finished = async (run: { getResult(): Promise<unknown> }, ms = 1500) => {
  const timeout = sleep(ms).then(() => "still running" as const);
  return Promise.race([run.getResult(), timeout]);
};
const rerunState = (coordinator: string) => DBOS.getEvent(coordinator, "stage-rerun-state") as Promise<{ status: string; code?: string } | null>;
/** The coordinator's rerun state once it reports a failed unit, or null after `ms`. */
const failedState = async (coordinator: string, ms = 1500) => {
  for (const deadline = Date.now() + ms; Date.now() < deadline; await sleep(10)) {
    const state = await rerunState(coordinator);
    if (state?.status === "waiting") return state;
  }
  return null;
};

test("a plan approved after its agent's session was closed is released and completes the unit", async () => {
  const { coordinator, run, request, execution } = await startStage();
  const plan = await emit(execution, request, planWriter, "plan");
  await settle();
  ends.get(request.execution_id)?.(CLOSED);
  await settle();
  expect((await rerunState(coordinator))?.status).not.toBe("waiting");
  await approve(execution, plan);
  const result = await finished(run) as { outcome: { kind: string }; artifacts: ArtifactRevision[] } | "still running";
  expect(result).not.toBe("still running");
  if (result === "still running") return;
  expect(result.outcome).toEqual({ kind: "succeeded" });
  expect(result.artifacts.map((artifact) => artifact.id)).toEqual([plan.id]);
});

test("a plan approved after its agent exited normally is released and completes the unit", async () => {
  const { coordinator, run, request, execution } = await startStage();
  const plan = await emit(execution, request, planWriter, "plan");
  await settle();
  ends.get(request.execution_id)?.(EXITED);
  await settle();
  expect((await rerunState(coordinator))?.status).not.toBe("waiting");
  await approve(execution, plan);
  const result = await finished(run) as { outcome: { kind: string } } | "still running";
  expect(result).not.toBe("still running");
  if (result === "still running") return;
  expect(result.outcome).toEqual({ kind: "succeeded" });
});

test("a plan approved while its agent is still running completes the unit", async () => {
  const { run, request, execution } = await startStage();
  const plan = await emit(execution, request, planWriter, "plan");
  await settle();
  await approve(execution, plan);
  const result = await finished(run) as { outcome: { kind: string } } | "still running";
  expect(result).not.toBe("still running");
  if (result === "still running") return;
  expect(result.outcome).toEqual({ kind: "succeeded" });
  expect(fenced).toEqual([request.execution_id]);
});

test("a session that closes without emitting the plan fails the unit as missing output", async () => {
  const { coordinator, request } = await startStage();
  await settle();
  ends.get(request.execution_id)?.(CLOSED);
  const state = await failedState(coordinator);
  expect(state?.status).toBe("waiting");
  expect(state?.code).toBe("required_output_missing");
});

test("an output never emitted fails the unit even while another output waits for review", async () => {
  const notes = { ...planWriter.outputs[0]!, name: "notes" };
  const twoOutputs = { ...planWriter, outputs: [...planWriter.outputs, notes] } as CompiledStageContract;
  const { coordinator, request, execution } = await startStage(twoOutputs);
  await emit(execution, request, twoOutputs, "plan");
  await settle();
  ends.get(request.execution_id)?.(CLOSED);
  const state = await failedState(coordinator);
  expect(state?.status).toBe("waiting");
  expect(state?.code).toBe("required_output_missing");
});

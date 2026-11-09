import { afterEach, expect, test } from "bun:test";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import type * as schema from "@agentclientprotocol/sdk";

import type { AgentProfile, AgentProfileId } from "../../../src/acp/agent-profile";
import { AcpControllerRegistry } from "../../../src/acp/controller-registry";
import { projectSessionUpdate } from "../../../src/acp/event-projector";
import { AcpProcessSupervisor } from "../../../src/acp/process-supervisor";
import { AcpSessionService } from "../../../src/acp/session-service";
import * as summaries from "../../../src/acp/session-summary";
import { AcpSessionStore } from "../../../src/acp/store";
import { ok, type AcpUiEvent, type KbblSessionId } from "../../../src/acp/types";
import { openTestDb } from "../../../src/db/test-db";

const AGENT = join(import.meta.dir, "compacting-agent.ts");
const NATIVE_SUMMARY = "# Native handoff\n\nThe agent's own compacted context.";
const sid = "00000000-0000-4000-8000-0000000000c1" as KbblSessionId;
const produced_at = "2026-11-07T00:00:00.000Z";

const services: AcpSessionService[] = [];
afterEach(async () => {
  for (const service of services.splice(0)) await service.shutdown();
});

/** A service with its default summary strategies, backed by the compacting fake agent. */
function compactingService(): { service: AcpSessionService; store: AcpSessionStore } {
  const store = new AcpSessionStore(openTestDb());
  const profile: AgentProfile = {
    id: "fake", label: "Compacting fake agent", command: process.execPath, args: [AGENT],
    env_policy: { inherit: true }, enabled: true, requireLoadSession: false, sessionMode: null,
  };
  const service = new AcpSessionService({
    store,
    controllers: new AcpControllerRegistry(),
    profiles: new Map<AgentProfileId, AgentProfile>([["fake", profile]]),
    supervisor: new AcpProcessSupervisor({ graceful_kill_ms: 1000, hard_kill_ms: 1000 }),
    worktrees: { resolve: async (_sid, spec) => ok({ worktree_path: spec.workdir, worktree_branch: null, worktree_base_ref: null, parent_sid: null }) },
    config: { default_agent: "fake", graceful_kill_ms: 1000, idle_child_ttl_ms: 900_000, live_event_buffer: 2000 },
  });
  services.push(service);
  return { service, store };
}

/** Run one session to the end of its initial turn, close it, and read the stored handoff. */
async function closedSummary(prompt: string) {
  const { service, store } = compactingService();
  const workdir = await mkdtemp(join(tmpdir(), "compacting-work-"));
  const ensured = await service.ensureResumableSession(`key-${prompt}`, { initial_prompt: prompt, workdir, runtime: "fake" });
  if (!ensured.ok) throw new Error(`ensure failed: ${ensured.error.detail}`);
  const id = ensured.value.session.sid;
  const observed = await service.observeInitialTurn(id, 8000);
  if (!observed.ok || observed.value.kind !== "succeeded") throw new Error("the initial turn did not succeed");
  await service.closeSession(id);
  const stored = store.getSessionSummary(id);
  return stored ? { method: stored.method, markdown: stored.markdown } : null;
}

type Generator = summaries.SessionSummaryGenerator;

function nativeGenerator(): Generator {
  const exported = (summaries as unknown as { NativeCompactionSummaryGenerator?: new () => Generator }).NativeCompactionSummaryGenerator;
  if (typeof exported !== "function") throw new Error("session-summary exports no NativeCompactionSummaryGenerator");
  return new exported();
}

const text = (value: string): schema.ContentBlock => ({ type: "text", text: value });
const user = (value: string): schema.SessionUpdate => ({ sessionUpdate: "user_message_chunk", content: text(value) });
const reply = (value: string): schema.SessionUpdate => ({ sessionUpdate: "agent_message_chunk", content: text(value) });
const chunk = (compactionId: string, value: string): schema.SessionUpdate => ({ sessionUpdate: "compaction_summary_chunk", compactionId, content: text(value) });
const compaction = (compactionId: string, status: string, summary?: string): schema.SessionUpdate => ({
  sessionUpdate: "compaction_update", compactionId, status,
  ...(summary === undefined ? {} : { summary: [text(summary)] }),
});

/** The events a live session holds after these updates, through kbbl's own projector. */
function events(...updates: schema.SessionUpdate[]): AcpUiEvent[] {
  return updates
    .map((update, index) => projectSessionUpdate(update, false, `chunk-${index}`))
    .filter((event): event is AcpUiEvent => event !== null);
}

async function handoff(...updates: schema.SessionUpdate[]) {
  const generated = await summaries.generateSessionSummary({ session_id: sid, produced_at, events: events(...updates) }, [
    nativeGenerator(), new summaries.ManualCompactionSummaryGenerator(), new summaries.FinalResponseSummaryGenerator(),
  ]);
  return generated.ok ? { method: generated.value.method, markdown: generated.value.markdown } : null;
}

test("reachability: a compacting agent's completed compaction becomes the session handoff on close", async () => {
  expect((await closedSummary("build the thing"))?.method).toBe("native_compaction");
}, 20_000);

test("reachability: the native summary wins over a manual /compact turn", async () => {
  expect((await closedSummary("/compact"))?.method).toBe("native_compaction");
}, 20_000);

test("semantics: the stored handoff is the text of the agent's completed summary", async () => {
  const native = { method: "native_compaction" as const, markdown: NATIVE_SUMMARY };
  expect([await closedSummary("build the thing"), await closedSummary("/compact")]).toEqual([native, native]);
}, 40_000);

test("semantics: the completed update's summary replaces the streamed chunks", async () => {
  const generated = await nativeGenerator().generate({ session_id: sid, produced_at, events: events(
    user("go"), compaction("c1", "in_progress"), chunk("c1", "draft"), compaction("c1", "completed", "final handoff"), reply("answer"),
  ) });
  expect(generated).toEqual({ ok: true, value: { schema_version: 1, session_id: sid, method: "native_compaction", produced_at, markdown: "final handoff" } });
});

test("semantics: without a summary on the completed update, the handoff is that compaction's own chunks", async () => {
  expect(await handoff(
    user("go"),
    compaction("c1", "in_progress"), chunk("c1", "old "), chunk("c1", "context"), compaction("c1", "completed"),
    compaction("c2", "in_progress"), chunk("c2", "new "), chunk("c2", "context"), compaction("c2", "completed"),
    reply("answer"),
  )).toEqual({ method: "native_compaction", markdown: "new context" });
});

test("semantics: a failed compaction yields no native summary, so the final response is kept", async () => {
  expect(await handoff(
    user("go"), compaction("c1", "in_progress"), chunk("c1", "partial"),
    { sessionUpdate: "compaction_update", compactionId: "c1", status: "failed", error: "context too large" }, reply("answer"),
  )).toEqual({ method: "final_response", markdown: "answer" });
});

test("semantics: an unfinished or cancelled compaction yields no native summary", async () => {
  const unfinished = await handoff(user("go"), compaction("c1", "in_progress"), chunk("c1", "partial"), reply("answer"));
  const cancelled = await handoff(user("go"), compaction("c2", "in_progress"), chunk("c2", "partial"), compaction("c2", "cancelled"), reply("answer"));
  expect([unfinished, cancelled]).toEqual([{ method: "final_response", markdown: "answer" }, { method: "final_response", markdown: "answer" }]);
});

async function expectEmptyHandoffFallsThrough(...updates: schema.SessionUpdate[]) {
  const generated = await nativeGenerator().generate({ session_id: sid, produced_at, events: events(...updates) });
  expect(generated.ok).toBe(false);
  expect(await handoff(...updates)).toEqual({ method: "final_response", markdown: "answer" });
}

test("semantics: a completed summary of only whitespace fails, so the next strategy runs", async () => {
  await expectEmptyHandoffFallsThrough(user("go"), compaction("c1", "in_progress"), compaction("c1", "completed", " \n "), reply("answer"));
});

test("semantics: a completed compaction with no summary and no chunks fails, so the next strategy runs", async () => {
  await expectEmptyHandoffFallsThrough(user("go"), compaction("c1", "in_progress"), compaction("c1", "completed"), reply("answer"));
});

test("semantics: the latest completed compaction wins", async () => {
  expect(await handoff(
    user("go"), compaction("c1", "completed", "first"), compaction("c2", "completed", "second"), reply("answer"),
  )).toEqual({ method: "native_compaction", markdown: "second" });
});

test("semantics: a compaction from an earlier turn is not the final turn's handoff", async () => {
  expect(await handoff(
    user("first"), compaction("c1", "completed", "stale"), reply("one"), user("second"), reply("two"),
  )).toEqual({ method: "final_response", markdown: "two" });
});

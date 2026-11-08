#!/usr/bin/env bun
// Hidden-check fake ACP agent, modelled on src/acp/__fixtures__/fake-acp-agent.ts: a real
// child process speaking ACP v1 over stdio through the SDK, that also reports context-window
// usage. A prompt is a list of directives separated by ";":
//
//   "usage <used> <size>"    → a usage_update, recorded in the transcript, so session/load
//                              replays it later.
//   "compact <used> <size>"  → a usage_update that is not recorded: the agent compacted its
//                              context, and the history it replays still holds older readings.
//   anything else            → no usage report.
//
// Every prompt is echoed as a recorded user chunk and answered with a recorded reply, then
// ends with end_turn. FAKE_ACP_STATE_DIR holds the transcripts across process restarts.

import { agent, ndJsonStream, PROTOCOL_VERSION, RequestError } from "@agentclientprotocol/sdk";
import type * as schema from "@agentclientprotocol/sdk";
import { randomUUID } from "node:crypto";
import { appendFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Readable, Writable } from "node:stream";

const stateDir = process.env.FAKE_ACP_STATE_DIR ?? join(tmpdir(), "fake-usage-state");
mkdirSync(stateDir, { recursive: true });

const transcriptPath = (sessionId: string) => join(stateDir, `${sessionId}.jsonl`);
const record = (sessionId: string, update: schema.SessionUpdate) =>
  appendFileSync(transcriptPath(sessionId), `${JSON.stringify(update)}\n`);

const app = agent({ name: "fake-usage-agent" })
  .onRequest("initialize", () => ({
    protocolVersion: PROTOCOL_VERSION,
    agentCapabilities: { loadSession: true, sessionCapabilities: { close: {}, additionalDirectories: {} } },
  }))
  .onRequest("session/new", () => {
    const sessionId = `fake-usage-${randomUUID()}`;
    appendFileSync(transcriptPath(sessionId), "");
    return { sessionId };
  })
  .onRequest("session/load", async (ctx) => {
    const { sessionId } = ctx.params;
    const path = transcriptPath(sessionId);
    if (!existsSync(path)) throw RequestError.resourceNotFound(sessionId);
    for (const line of readFileSync(path, "utf8").split("\n")) {
      if (line.trim().length === 0) continue;
      await ctx.client.notify("session/update", { sessionId, update: JSON.parse(line) as schema.SessionUpdate });
    }
    return {};
  })
  .onRequest("session/close", () => ({}))
  .onNotification("session/cancel", () => {})
  .onRequest("session/prompt", async (ctx) => {
    const { sessionId, prompt } = ctx.params;
    const text = prompt.map((block) => (block.type === "text" ? block.text : "")).join("");
    const send = async (update: schema.SessionUpdate, recorded: boolean) => {
      if (recorded) record(sessionId, update);
      await ctx.client.notify("session/update", { sessionId, update });
    };
    await send({ sessionUpdate: "user_message_chunk", content: { type: "text", text } }, true);
    for (const directive of text.split(";")) {
      const [verb, used, size] = directive.trim().split(/\s+/);
      if ((verb === "usage" || verb === "compact") && used !== undefined && size !== undefined) {
        await send({ sessionUpdate: "usage_update", used: Number(used), size: Number(size) }, verb === "usage");
      }
    }
    await send({ sessionUpdate: "agent_message_chunk", content: { type: "text", text: `fake reply to: ${text}` } }, true);
    return { stopReason: "end_turn" as const };
  });

app.connect(
  ndJsonStream(
    Writable.toWeb(process.stdout) as WritableStream<Uint8Array>,
    Readable.toWeb(process.stdin) as unknown as ReadableStream<Uint8Array>,
  ),
);

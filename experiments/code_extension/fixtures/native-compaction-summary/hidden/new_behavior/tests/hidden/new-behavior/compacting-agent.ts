#!/usr/bin/env bun
// A fake ACP agent that compacts its context during every prompt, modelled on kbbl's
// own fake agent. Like a compliant agent, it sends compaction updates only when the
// client advertised `clientCapabilities.session.compaction` at initialize. Each prompt:
// echo the prompt, compact (in progress, one streamed draft chunk, then completed with
// the authoritative summary), then answer. No network, no state on disk.

import { agent, ndJsonStream, PROTOCOL_VERSION, type AgentContext } from "@agentclientprotocol/sdk";
import type * as schema from "@agentclientprotocol/sdk";
import { randomUUID } from "node:crypto";
import { Readable, Writable } from "node:stream";

const NATIVE_SUMMARY = "# Native handoff\n\nThe agent's own compacted context.";

let compactionAdvertised = false;
let compactions = 0;

async function send(client: AgentContext, sessionId: string, update: schema.SessionUpdate): Promise<void> {
  await client.notify("session/update", { sessionId, update });
}

const app = agent({ name: "fake-acp-compacting" })
  .onRequest("initialize", (ctx) => {
    compactionAdvertised = ctx.params.clientCapabilities?.session?.compaction != null;
    return {
      protocolVersion: PROTOCOL_VERSION,
      agentCapabilities: { loadSession: false, sessionCapabilities: { close: {} } },
    };
  })
  .onRequest("session/new", () => ({ sessionId: `fake-${randomUUID()}` }))
  .onRequest("session/close", () => ({}))
  .onNotification("session/cancel", () => undefined)
  .onRequest("session/prompt", async (ctx) => {
    const { sessionId, prompt } = ctx.params;
    const text = prompt.map((block) => (block.type === "text" ? block.text : `[${block.type}]`)).join("");
    await send(ctx.client, sessionId, { sessionUpdate: "user_message_chunk", content: { type: "text", text } });
    if (compactionAdvertised) {
      compactions += 1;
      const compactionId = `compaction-${compactions}`;
      await send(ctx.client, sessionId, { sessionUpdate: "compaction_update", compactionId, status: "in_progress" });
      await send(ctx.client, sessionId, {
        sessionUpdate: "compaction_summary_chunk", compactionId, content: { type: "text", text: "draft summary" },
      });
      await send(ctx.client, sessionId, {
        sessionUpdate: "compaction_update", compactionId, status: "completed",
        summary: [{ type: "text", text: NATIVE_SUMMARY }],
      });
    }
    await send(ctx.client, sessionId, {
      sessionUpdate: "agent_message_chunk", content: { type: "text", text: `fake reply to: ${text}` },
    });
    return { stopReason: "end_turn" as const };
  });

if (import.meta.main) {
  app.connect(
    ndJsonStream(
      Writable.toWeb(process.stdout) as WritableStream<Uint8Array>,
      Readable.toWeb(process.stdin) as unknown as ReadableStream<Uint8Array>,
    ),
  );
}

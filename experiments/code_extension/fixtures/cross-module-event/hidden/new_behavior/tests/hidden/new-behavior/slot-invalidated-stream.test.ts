import { expect, test } from "bun:test";
import { PostgresOperatorProjectionRepository } from "../../../src/storage/postgres-operators";
import { createInvalidationEventApp } from "../../../src/http/invalidation-events";
import type { SqlExecutor } from "../../../src/storage/sql-executor";
import type { WorkflowRunId } from "../../../src/domain/primitives";

const SLOT_ROW = {
  sequence: "7",
  operation: "slot_invalidated",
  run_id: "11111111-1111-4111-8111-111111111111",
  run_unit_id: "22222222-2222-4222-8222-222222222222",
  stage_instance_id: "33333333-3333-4333-8333-333333333333",
  stage_key: "build",
  unit_id: "unit-1",
  work_order_id: null,
  wait_id: null,
  output_name: "report",
  collection_key: null,
  artifact_revision_id: null,
  attention: null,
  continuation: null,
  detail: { invalidation_kind: "input_revised" },
  superseded_by: "44444444-4444-4444-8444-444444444444",
  created_at: "2026-02-02T00:00:00.000Z",
};

/** Captures the statement so the producer's own projection can be inspected. */
const recordingExecutor = (rows: readonly object[]) => {
  const statements: string[] = [];
  const sql: SqlExecutor = {
    query: async <Row extends object>(statement: string): Promise<readonly Row[]> => {
      statements.push(statement);
      return rows as readonly Row[];
    },
  };
  return { sql, statements };
};

/** Read frames until `predicate` is satisfied or the stream runs dry. */
const readUntil = async (
  body: ReadableStream<Uint8Array> | null,
  predicate: (text: string) => boolean,
): Promise<string> => {
  const reader = body?.getReader();
  const decoder = new TextDecoder();
  let text = "";
  try {
    for (let frame = 0; frame < 20; frame += 1) {
      const chunk = await reader?.read();
      if (!chunk || chunk.done) break;
      text += decoder.decode(chunk.value);
      if (predicate(text)) break;
    }
  } finally {
    await reader?.cancel();
  }
  return text;
};

test("the real producer emits the invalidated slot as its own operation", async () => {
  const { sql } = recordingExecutor([SLOT_ROW]);
  const repository = new PostgresOperatorProjectionRepository(sql, "test-version");
  const [event] = await repository.list_run_events({
    after_sequence: null,
    limit: 10,
    run_id: null,
  });
  expect(event?.operation).toBe("slot_invalidated");
});

test("the producer selects the superseding revision for the projection", async () => {
  const { sql, statements } = recordingExecutor([SLOT_ROW]);
  const repository = new PostgresOperatorProjectionRepository(sql, "test-version");
  await repository.list_run_events({ after_sequence: null, limit: 10, run_id: null });
  expect(statements.join("\n")).toContain("superseded_by");
});

test("the producer's event carries the superseding revision to its consumer", async () => {
  const { sql } = recordingExecutor([SLOT_ROW]);
  const repository = new PostgresOperatorProjectionRepository(sql, "test-version");
  const [event] = await repository.list_run_events({
    after_sequence: null,
    limit: 10,
    run_id: null,
  });
  if (event?.operation !== "slot_invalidated") throw new Error("expected a slot_invalidated event");
  expect(event.payload.superseded_by as string | null).toBe("44444444-4444-4444-8444-444444444444");
});

test("the real consumer streams an invalidated slot on its own named frame", async () => {
  const { sql } = recordingExecutor([SLOT_ROW]);
  const repository = new PostgresOperatorProjectionRepository(sql, "test-version");
  let served = false;
  const app = createInvalidationEventApp({
    current_cursor: async () => "cursor:7",
    poll_interval_ms: 1,
    heartbeat_interval_ms: 60_000,
    list_run_events: async (after, limit) => {
      if (served) return [];
      served = true;
      return repository.list_run_events({
        after_sequence: after,
        limit,
        run_id: null as unknown as WorkflowRunId | null,
      });
    },
  });
  const response = await app.request("/events", { headers: { "last-event-id": "1" } });
  const text = await readUntil(response.body, (frames) => frames.includes("slot_invalidated"));
  expect(text).toContain("event: slot_invalidated");
});

test("an invalidated slot is not announced on the generic run event frame", async () => {
  const { sql } = recordingExecutor([SLOT_ROW]);
  const repository = new PostgresOperatorProjectionRepository(sql, "test-version");
  let served = false;
  const app = createInvalidationEventApp({
    current_cursor: async () => "cursor:7",
    poll_interval_ms: 1,
    heartbeat_interval_ms: 60_000,
    list_run_events: async (after, limit) => {
      if (served) return [];
      served = true;
      return repository.list_run_events({
        after_sequence: after,
        limit,
        run_id: null as unknown as WorkflowRunId | null,
      });
    },
  });
  const response = await app.request("/events", { headers: { "last-event-id": "1" } });
  const text = await readUntil(response.body, (frames) => frames.includes("slot_invalidated"));
  expect(text).not.toContain("event: run_event");
});

import { expect, test } from "bun:test";
import { DataUnavailable, HttpDataSource, InlineDataSource } from "../../src/data";
import type { ExportData } from "../../src/types";

const payload: ExportData = {
  schema_version: "assay-review-export/0.1.0", root_ref: "sha256:root",
  store: { root: null, runs: [], reports: [], issues: [] }, views: {}, objects: {}, capabilities: {},
};

test("inline source never falls back to fetch", async () => {
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = (() => { calls += 1; throw new Error("network attempted"); }) as unknown as typeof fetch;
  try {
    await expect(new InlineDataSource(payload).run("absent")).rejects.toBeInstanceOf(DataUnavailable);
    expect(calls).toBe(0);
  } finally { globalThis.fetch = original; }
});

test("inline source accepts canonical exported API keys", async () => {
  const runKey = "sha256:run";
  const data = {
    ...payload,
    views: {
      [`/api/runs/${encodeURIComponent(runKey)}`]: { summary: { run_id: "run" } },
      "/api/ambiguities": [],
    },
  } as unknown as ExportData;
  expect((await new InlineDataSource(data).run(runKey)).summary.run_id).toBe("run");
  expect(await new InlineDataSource(data).ambiguities()).toEqual([]);
});

test("HTTP source preserves structured missing-resource errors", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify({
    error: { code: "not_found", message: "run was not found", ref: "sha256:missing" },
  }), { status: 404, headers: { "content-type": "application/json" } })) as unknown as typeof fetch;
  try {
    await expect(new HttpDataSource().run("sha256:missing")).rejects.toThrow(
      "run was not found (sha256:missing)",
    );
  } finally { globalThis.fetch = original; }
});

test("HTTP source distinguishes an unsupported route", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = (async () => new Response(JSON.stringify({
    error: { code: "not_found", message: "API route was not found", ref: null },
  }), { status: 404, headers: { "content-type": "application/json" } })) as unknown as typeof fetch;
  try {
    await expect(new HttpDataSource().run("sha256:missing")).rejects.toBeInstanceOf(
      DataUnavailable,
    );
  } finally { globalThis.fetch = original; }
});

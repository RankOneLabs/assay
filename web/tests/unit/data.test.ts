import { expect, test } from "bun:test";
import { DataUnavailable, InlineDataSource } from "../../src/data";
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

import { expect, test } from "bun:test";
import { OfflineDataSource } from "../../src/offline";
import type { ExportData } from "../../src/types";

test("offline pairs use the declared arm route and hydrate cell view keys", async () => {
  const runKey = "sha256:run";
  const cellPath = `/api/runs/${encodeURIComponent(runKey)}/cells/subject%3Abaseline%3Aw0`;
  const pairPath = `/api/runs/${encodeURIComponent(runKey)}/pairs/subject?reference=baseline&candidate=treatment`;
  const cell = { summary: { cell_id: "subject:baseline:w0" } };
  const pair = {
    run_key: runKey, subject_id: "subject", subject_label: "Subject",
    reference_arm: "baseline", candidate_arm: "treatment",
    reference_cells: [cellPath], candidate_cells: [cellPath],
    treatment_diff: {}, output_diffs: [], issues: [],
  };
  const data = {
    schema_version: "assay-review-export/0.1.0", root_ref: runKey,
    store: { root: null, runs: [], reports: [], issues: [] },
    views: { [cellPath]: cell, [pairPath]: pair }, objects: {}, capabilities: {},
  } as unknown as ExportData;

  const hydrated = await new OfflineDataSource(data).pair(
    runKey, "subject", "baseline", "treatment",
  );

  expect(hydrated.reference_arm).toBe("baseline");
  expect(hydrated.candidate_arm).toBe("treatment");
  expect(hydrated.reference_cells[0]?.summary.cell_id).toBe("subject:baseline:w0");
});

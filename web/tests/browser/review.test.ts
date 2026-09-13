import { afterAll, beforeAll, expect, test } from "bun:test";
import { chromium, type Browser, type Page } from "playwright";

const STATIC = new URL("../../../src/assay/review/static/", import.meta.url);
const hostile = "</script><script>window.pwned=true</script>";
const runKey = "loose/run:key";
let browser: Browser;
let page: Page;
let recomputes = 0;
const origin = "http://assay.test";

const issue = { code: "partial", message: "one value is unavailable", ref: null, coordinate_id: null };
const cost = { coverage: "mixed", coverage_counts: { measured: 3, unavailable: 1 }, amounts: { USD: 1.25 }, by_stage_arm: {}, attempts: 4, expected_attempts: 5, unaccounted_attempts: 1, partial: true, issues: [issue] };
const verdict = (value: string | null, failures: string[] = []) => ({ evaluator_id: "correctness", values: [value], repeat_statuses: failures.length ? ["failed"] : ["succeeded"], failures, agreed: failures.length ? null : true, categories: ["incorrect", "correct"] });
const cells = [
  { cell_id: "ok", subject_id: "success", arm_id: "candidate", worker_repeat: 0, status: "succeeded", error_type: null, error_message: null, record_refs: [], exclusion: null, verdicts: [verdict("correct")], issues: [] },
  { cell_id: "neg", subject_id: "negative", arm_id: "candidate", worker_repeat: 0, status: "succeeded", error_type: null, error_message: null, record_refs: [], exclusion: null, verdicts: [verdict("incorrect")], issues: [] },
  { cell_id: "amb", subject_id: "ambiguous", arm_id: "candidate", worker_repeat: 0, status: "succeeded", error_type: null, error_message: null, record_refs: [], exclusion: null, verdicts: [verdict(null, ["AmbiguousStructure: unclear"])], issues: [] },
  { cell_id: "fail", subject_id: "failed", arm_id: "candidate", worker_repeat: 0, status: "failed", error_type: "WorkerFailure", error_message: hostile, record_refs: [], exclusion: null, verdicts: [], issues: [] },
  { cell_id: "missing", subject_id: "missing", arm_id: "candidate", worker_repeat: 0, status: "missing", error_type: null, error_message: null, record_refs: [], exclusion: null, verdicts: [], issues: [] },
];
const runSummary = { run_key: runKey, run_id: hostile, manifest_ref: "sha256:manifest", plan_ref: "sha256:plan", snapshot_ref: null, status: "incomplete", subjects: 5, arms: ["candidate"], worker_repeats: 1, concurrency: 1, jig_revision: "fixture", assay_version: "1", started_at: null, completed_at: null, cells_total: 5, cells_succeeded: 3, cells_failed: 1, cells_missing: 1, cells_invalid: 0, cells_conflicted: 0, evaluations_total: 3, evaluations_succeeded: 2, evaluations_failed: 1, evaluations_missing: 0, evaluations_invalid: 0, evaluations_conflicted: 0, exclusions: [], cost, issues: [issue] };
const reportSummary = { report_ref: "sha256:report", config_ref: "sha256:config", metric: "ordinal", evaluator_id: "correctness", reference_arm: "reference", candidates: ["candidate"], engine_version: "1", recomputable: true, recompute_disabled_reason: null, manifest_refs: ["sha256:manifest"], issues: [] };
const store = { root: "/fixture", runs: [runSummary], reports: [reportSummary], issues: [] };
const run = { summary: runSummary, subjects: cells.map((cell) => ({ id: cell.subject_id, label: cell.subject_id, digest: `sha256:${cell.subject_id}`, partition: "test" })), arms: [{ id: "candidate", worker_id: "worker", worker_version: "1", intervention_keys: [] }], evaluators: [{ id: "correctness", identity: {}, repeats: 1, categories: ["incorrect", "correct"] }], cells, missing_coordinates: ["worker:missing"], cost_estimate: null };
const cellDetail = { summary: cells[0], input_ref: null, input_preview: { kind: "consistency", instruction: hostile, files: { "unsafe/<file>.py": hostile }, artifact: null }, output_ref: "sha256:out", output_text: hostile, output_preview: null, trace_ref: null, trace_preview: null, recorded_prompt: null, recorded_prompt_ref: null, evaluations: [{ run_key: runKey, cell_id: "ok", coordinate_id: "coord", evaluator_id: "correctness", evaluator_repeat: 0, status: "succeeded", record_refs: [], verdict: "correct", reason_codes: [], error_type: null, error_message: null, detail_refs: [], detail: { diagnostic: hostile }, issues: [] }], started_at: null, completed_at: null };
const pair = { run_key: runKey, subject_id: "success", subject_label: "success", reference_arm: "reference", candidate_arm: "candidate", reference_cells: [], candidate_cells: [cellDetail], treatment_diff: { left_ref: null, right_ref: "sha256:input", left_text: null, right_text: hostile, unified: null, unavailable_reason: "Reference excluded by the persisted study." }, output_diffs: [{ left_ref: "sha256:left", right_ref: "sha256:right", left_text: "old", right_text: "new", unified: "-old\n+new", unavailable_reason: null }], issues: [] };
const report = { summary: reportSummary, report: { inference_floor: 10 }, comparisons: [{ kind: "ordinal", reference: "reference", candidate: "candidate", values: { categories: ["incorrect", "correct"], counts: { correct: 4, incorrect: 1 } } }], missingness: { candidate: { missing: 1 } }, exclusions: [{ subject_id: "s0", arm_id: "candidate", classification: "invalid", reason: hostile, manifest_ref: null }], costs: cost, subject_labels: {} };
const ambiguity = [{ ...cellDetail.evaluations[0], cell_id: "amb", status: "failed", error_type: "AmbiguousStructure", error_message: hostile }];

const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
const handleRequest = async (request: Request): Promise<Response> => {
  const url = new URL(request.url);
  if (url.pathname === "/") return new Response(Bun.file(new URL("index.html", STATIC)), { headers: { "content-type": "text/html" } });
  if (url.pathname === "/app.js") return new Response(Bun.file(new URL("app.js", STATIC)), { headers: { "content-type": "text/javascript" } });
  if (url.pathname === "/app.css") return new Response(Bun.file(new URL("app.css", STATIC)), { headers: { "content-type": "text/css" } });
  if (url.pathname === "/api/store") return json(store);
  if (url.pathname === "/api/ambiguities") return json(ambiguity);
  if (url.pathname.includes("/recompute")) { recomputes += 1; await Bun.sleep(120); return json({ status: "matched", matched: true, stored_digest: "sha256:report", recomputed_digest: "sha256:report", reason: null }); }
  if (url.pathname.endsWith("/pairs/missing")) return json({ ...pair, subject_id: "missing" });
  if (url.pathname.includes("/pairs/")) return json(pair);
  if (url.pathname.endsWith("/cells/fail")) return json({ ...cellDetail, summary: cells[3], evaluations: [] });
  if (url.pathname.endsWith("/cells/missing")) return json({ ...cellDetail, summary: cells[4], evaluations: [] });
  if (url.pathname.includes("/cells/")) return json(cellDetail);
  if (url.pathname.startsWith("/api/reports/")) return json(report);
  if (url.pathname.startsWith("/api/runs/")) return json({ ...run, summary: { ...run.summary, exclusions: [{ subject_id: "success", arm_id: "reference", classification: "excluded", reason: "Outside study population", manifest_ref: null }] } });
  return new Response("absent", { status: 404 });
};

beforeAll(async () => {
  browser = await chromium.launch({ ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}), headless: true });
  page = await browser.newPage();
  await page.route("**/*", async (route) => {
    const response = await handleRequest(new Request(route.request().url(), { method: route.request().method() }));
    await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers), body: Buffer.from(await response.arrayBuffer()) });
  });
});
afterAll(async () => { if (browser) await browser.close(); });

async function textOf(selector: string): Promise<string | null> {
  const locator = page.locator(selector);
  await locator.waitFor({ state: "visible" });
  return locator.textContent();
}

test("committed bundle renders every view and safe keyboard links", async () => {
  await page.goto(origin);
  expect(await textOf("h1")).toBe("Runs and reports");
  await page.locator(".summary-card a").focus(); await page.keyboard.press("Enter");
  await page.locator(".cell-grid").waitFor({ state: "visible" });
  for (const selector of [".status-succeeded", ".status-negative", ".status-ambiguous", ".status-failed", ".status-missing"]) await page.locator(selector).last().waitFor({ state: "visible" });
  expect(await page.locator("script").count()).toBe(1);
  await page.locator(".cell-grid .status-succeeded").focus(); await page.keyboard.press("Enter");
  await page.getByText(hostile, { exact: true }).first().waitFor({ state: "visible" });

  await page.goto(`${origin}/#/runs/${encodeURIComponent(runKey)}/pairs/success`);
  await page.locator("h2").nth(1).waitFor({ state: "visible" });
  expect(await page.locator("h2").nth(1).textContent()).toBe("Treatment diff");
  await page.getByText("Reference excluded by the persisted study.").waitFor({ state: "visible" });

  await page.goto(`${origin}/#/reports/${encodeURIComponent("sha256:report")}`);
  await page.locator(".ordinal li").first().waitFor({ state: "visible" });
  expect(await page.locator(".ordinal li").allTextContents()).toEqual(["incorrect: 1", "correct: 4"]);
  await page.locator("button").evaluate((button: HTMLButtonElement) => { button.click(); button.click(); });
  await page.getByText("Recomputing…").waitFor({ state: "visible" });
  expect(await textOf(".recompute-result strong")).toBe("matched");
  expect(recomputes).toBe(1);

  await page.goto(`${origin}/#/ambiguities`);
  await page.locator(".ambiguity-list a").focus(); await page.keyboard.press("Enter");
  await page.waitForFunction(() => document.querySelector("h1")?.textContent === "ok");
  expect(await textOf("h1")).toBe("ok");
}, 20_000);

test("unknown fragments have a local unavailable state", async () => {
  await page.goto(`${origin}/#/unknown`);
  await page.locator(".state-unavailable").waitFor({ state: "visible" });
}, 10_000);

for (const cellId of ["fail", "missing"]) {
  test(`${cellId} cell without evaluations links back to its run`, async () => {
    await page.goto(`${origin}/#/runs/${encodeURIComponent(runKey)}/cells/${cellId}`);
    await page.getByText("No evaluations recorded.").waitFor();
    const back = page.getByRole("link", { name: "Back to cell grid" });
    expect(await back.getAttribute("href")).toBe(`#/runs/${encodeURIComponent(runKey)}`);
    await back.focus();
    await page.keyboard.press("Enter");
    await page.locator(".cell-grid").waitFor();
    expect(await page.locator(".state-unavailable").count()).toBe(0);
  });
}

test("empty pair sides distinguish exclusions from missing cells", async () => {
  await page.goto(`${origin}/#/runs/${encodeURIComponent(runKey)}/pairs/success`);
  expect(await textOf(".pair-side .unavailable-inline")).toBe("Excluded: Outside study population");
  await page.goto(`${origin}/#/runs/${encodeURIComponent(runKey)}/pairs/missing`);
  await page.waitForFunction(() => document.querySelector(".pair-side .unavailable-inline")?.textContent?.startsWith("Missing:"));
  expect(await textOf(".pair-side .unavailable-inline")).toBe("Missing: no cell was recorded for this side.");
});

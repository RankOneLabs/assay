import { DataUnavailable, dataSourceFromDocument, type DataSource } from "./data";
import { addDefinition, appendText, element, localLink, renderJson, section } from "./dom";
import { cellFragment, pairFragment, parseRoute, reportFragment, runFragment, type Route } from "./routes";
import type {
  CellDetail, CellSummary, ComparisonView, CostView, DiffView, Issue, PairView, ReportDetail,
  RecomputeResult, RunDetail, StoreSummary, VerdictSummary, Json,
} from "./types";

export type GridState = "succeeded" | "negative" | "ambiguous" | "failed" | "missing" | "excluded" | "invalid" | "conflicted";

const NEGATIVE = new Set<unknown>([false, 0, "incorrect", "failed", "fail", "negative"]);

export function gridState(cell: CellSummary): GridState {
  if (cell.status !== "succeeded") return cell.status;
  if (cell.verdicts.some((verdict) => verdict.failures.some((failure) => failure.includes("AmbiguousStructure")))) return "ambiguous";
  if (cell.verdicts.some((verdict) => verdict.repeat_statuses.includes("failed") && verdict.values.every((value) => value === null))) return "ambiguous";
  if (cell.verdicts.some((verdict) => verdict.values.some((value) => NEGATIVE.has(value)))) return "negative";
  return "succeeded";
}

export function orderedCategories<T>(declared: readonly string[], values: Record<string, T>): [string, T | undefined][] {
  return declared.map((category) => [category, values[category]]);
}

const STATE_LABEL: Record<GridState, string> = {
  succeeded: "Succeeded", negative: "Negative verdict", ambiguous: "Ambiguous evaluation",
  failed: "Worker failed", missing: "Missing", excluded: "Excluded", invalid: "Invalid", conflicted: "Conflicted",
};

function clearAndTitle(root: HTMLElement, eyebrow: string, title: unknown): void {
  root.replaceChildren();
  const header = element("header", { className: "view-title" });
  header.append(element("p", { className: "eyebrow", text: eyebrow }), element("h1", { text: title }));
  root.append(header);
}

function statePage(root: HTMLElement, kind: "loading" | "empty" | "unavailable" | "error", message: unknown): void {
  root.replaceChildren();
  const panel = element("section", { className: `state panel state-${kind}` });
  panel.setAttribute("role", kind === "error" ? "alert" : "status");
  panel.append(element("h1", { text: kind[0]!.toUpperCase() + kind.slice(1) }), element("p", { text: message }));
  root.append(panel);
}

function issuesBlock(issues: Issue[]): HTMLElement | null {
  if (!issues.length) return null;
  const aside = element("aside", { className: "issues" });
  aside.append(element("h3", { text: "Data issues" }));
  const list = element("ul");
  for (const issue of issues) {
    const item = element("li");
    item.append(element("strong", { text: issue.code }), element("span", { text: ": " }));
    appendText(item, issue.message);
    if (issue.ref) item.append(element("code", { text: issue.ref }));
    list.append(item);
  }
  aside.append(list);
  return aside;
}

function verdictText(verdicts: VerdictSummary[]): string {
  if (!verdicts.length) return "No evaluation";
  return verdicts.map((verdict) => {
    const values = verdict.values.map((value) => value ?? "missing").join(", ");
    return `${verdict.evaluator_id}: ${values}`;
  }).join(" · ");
}

function renderBrowser(root: HTMLElement, store: StoreSummary): void {
  clearAndTitle(root, "Evidence browser", "Runs and reports");
  if (!store.runs.length && !store.reports.length) {
    statePage(root, "empty", "No runs or reports were found.");
    return;
  }
  const runPanel = section("Runs");
  if (!store.runs.length) runPanel.append(element("p", { className: "empty-inline", text: "No runs found." }));
  else {
    const cards = element("div", { className: "card-list" });
    for (const run of store.runs) {
      const article = element("article", { className: "summary-card" });
      const heading = element("h3");
      heading.append(localLink(run.run_id, runFragment(run.run_key)));
      const counts = element("p", { className: "counts", text: `${run.cells_succeeded} succeeded · ${run.cells_failed} failed · ${run.cells_missing ?? "unknown"} missing` });
      article.append(heading, element("p", { className: `badge status-${run.status}`, text: run.status }), counts);
      const issue = issuesBlock(run.issues); if (issue) article.append(issue);
      cards.append(article);
    }
    runPanel.append(cards);
  }
  const reportPanel = section("Reports");
  if (!store.reports.length) reportPanel.append(element("p", { className: "empty-inline", text: "No reports found." }));
  else {
    const list = element("ul", { className: "link-list" });
    for (const report of store.reports) {
      const item = element("li");
      item.append(localLink(`${report.metric} · ${report.evaluator_id}`, reportFragment(report.report_ref)));
      item.append(element("span", { className: "mono", text: report.report_ref }));
      list.append(item);
    }
    reportPanel.append(list);
  }
  root.append(runPanel, reportPanel);
  const issue = issuesBlock(store.issues); if (issue) root.append(issue);
}

function renderGrid(root: HTMLElement, run: RunDetail): void {
  clearAndTitle(root, run.summary.status, run.summary.run_id);
  if (!run.subjects.length || !run.arms.length) {
    root.append(element("section", { className: "state panel state-empty", text: "This run has no cells to display." }));
    return;
  }
  const meta = element("dl", { className: "metadata" });
  addDefinition(meta, "Run key", run.summary.run_key);
  addDefinition(meta, "Jig revision", run.summary.jig_revision);
  addDefinition(meta, "Cost coverage", run.summary.cost.coverage);
  root.append(meta);

  const wrapper = element("div", { className: "grid-scroll panel" });
  const table = element("table", { className: "cell-grid" });
  const head = element("thead"); const headerRow = element("tr");
  headerRow.append(element("th", { text: "Subject" }));
  const repeats = run.summary.worker_repeats ?? Math.max(1, ...run.cells.map((cell) => cell.worker_repeat + 1));
  for (const arm of run.arms) for (let repeat = 0; repeat < repeats; repeat += 1) {
    headerRow.append(element("th", { text: `${arm.id} · repeat ${repeat + 1}` }));
  }
  head.append(headerRow); table.append(head);
  const body = element("tbody");
  for (const subject of run.subjects) {
    const row = element("tr");
    const subjectHead = element("th");
    subjectHead.append(localLink(subject.label, pairFragment(run.summary.run_key, subject.id)));
    row.append(subjectHead);
    for (const arm of run.arms) for (let repeat = 0; repeat < repeats; repeat += 1) {
      const cell = run.cells.find((candidate) => candidate.subject_id === subject.id && candidate.arm_id === arm.id && candidate.worker_repeat === repeat);
      const td = element("td");
      if (!cell) td.append(element("span", { className: "cell-state status-missing", text: "Missing" }));
      else {
        const state = gridState(cell);
        const link = localLink(STATE_LABEL[state], cellFragment(run.summary.run_key, cell.cell_id));
        link.className = `cell-state status-${state}`;
        link.append(element("small", { text: verdictText(cell.verdicts) }));
        td.append(link);
      }
      row.append(td);
    }
    body.append(row);
  }
  table.append(body); wrapper.append(table); root.append(wrapper);
  if (run.missing_coordinates?.length) {
    const missing = section("Missing coordinates");
    const list = element("ul"); for (const coordinate of run.missing_coordinates) list.append(element("li", { text: coordinate }));
    missing.append(list); root.append(missing);
  }
  const issue = issuesBlock(run.summary.issues); if (issue) root.append(issue);
}

function previewBlock(title: string, ref: string | null, text: string | null, reason?: string | null): HTMLElement {
  const panel = section(title);
  if (reason) panel.append(element("p", { className: "unavailable-inline", text: reason }));
  else if (text === null) panel.append(element("p", { className: "empty-inline", text: "No content recorded." }));
  else panel.append(element("pre", { className: "code", text }));
  if (ref) panel.append(element("p", { className: "mono", text: ref }));
  return panel;
}

function renderCell(root: HTMLElement, cell: CellDetail): void {
  clearAndTitle(root, STATE_LABEL[gridState(cell.summary)], cell.summary.cell_id);
  const back = localLink("Back to cell grid", runFragment(cell.evaluations[0]?.run_key ?? ""));
  back.className = "back-link"; root.append(back);
  const input = section("Realization input");
  if (cell.input_preview.instruction) input.append(element("p", { text: cell.input_preview.instruction }));
  if (cell.input_preview.files) for (const [path, content] of Object.entries(cell.input_preview.files)) {
    input.append(element("h3", { text: path }), element("pre", { className: "code", text: content }));
  }
  if (!cell.input_preview.instruction && !cell.input_preview.files) input.append(element("p", { className: "unavailable-inline", text: "Input unavailable." }));
  root.append(input, previewBlock("Worker output", cell.output_ref, cell.output_text, cell.summary.error_message));
  const evaluations = section("Evaluations");
  if (!cell.evaluations.length) evaluations.append(element("p", { className: "empty-inline", text: "No evaluations recorded." }));
  for (const evaluation of cell.evaluations) {
    const article = element("article", { className: "evaluation" });
    article.append(element("h3", { text: `${evaluation.evaluator_id} · repeat ${evaluation.evaluator_repeat + 1}` }), element("p", { className: `badge status-${evaluation.status}`, text: evaluation.status }));
    if (evaluation.verdict !== null) article.append(element("p", { text: evaluation.verdict }));
    if (evaluation.error_type) article.append(element("p", { className: "diagnostic", text: `${evaluation.error_type}: ${evaluation.error_message ?? "No detail"}` }));
    if (evaluation.detail !== null) article.append(renderJson(evaluation.detail));
    const issue = issuesBlock(evaluation.issues); if (issue) article.append(issue);
    evaluations.append(article);
  }
  root.append(evaluations);
}

function diffPanel(title: string, diff: DiffView): HTMLElement {
  const panel = section(title);
  if (diff.unavailable_reason) {
    panel.append(element("p", { className: "unavailable-inline", text: diff.unavailable_reason }));
    return panel;
  }
  const sides = element("div", { className: "diff-sides" });
  sides.append(previewBlock("Reference", diff.left_ref, diff.left_text), previewBlock("Candidate", diff.right_ref, diff.right_text));
  panel.append(sides);
  if (diff.unified) panel.append(element("details", { className: "unified" }));
  const details = panel.querySelector("details");
  if (details && diff.unified) details.append(element("summary", { text: "Unified diff" }), element("pre", { className: "code", text: diff.unified }));
  return panel;
}

function sideAvailability(pair: PairView, cells: CellDetail[], label: string): HTMLElement {
  const block = element("div", { className: "pair-side" });
  block.append(element("h3", { text: label }));
  if (!cells.length) block.append(element("p", { className: "unavailable-inline", text: "Missing or excluded: no cell is available for this side." }));
  else for (const cell of cells) {
    const state = gridState(cell.summary);
    block.append(element("p", { className: `badge status-${state}`, text: `Repeat ${cell.summary.worker_repeat + 1}: ${STATE_LABEL[state]}` }));
    if (cell.summary.error_message) block.append(element("p", { className: "diagnostic", text: cell.summary.error_message }));
  }
  return block;
}

function renderPair(root: HTMLElement, pair: PairView): void {
  clearAndTitle(root, "Paired subject", pair.subject_label ?? pair.subject_id);
  root.append(localLink("Back to cell grid", runFragment(pair.run_key)));
  const availability = section("Pair availability");
  const sides = element("div", { className: "diff-sides" });
  sides.append(sideAvailability(pair, pair.reference_cells, pair.reference_arm), sideAvailability(pair, pair.candidate_cells, pair.candidate_arm));
  availability.append(sides); root.append(availability);
  root.append(diffPanel("Treatment diff", pair.treatment_diff));
  if (!pair.output_diffs.length) root.append(element("section", { className: "state panel state-empty", text: "No output diffs are available." }));
  else pair.output_diffs.forEach((diff, index) => root.append(diffPanel(`Output diff · repeat ${index + 1}`, diff)));
  const issue = issuesBlock(pair.issues); if (issue) root.append(issue);
}

function renderCost(cost: CostView): HTMLElement {
  const panel = section("Cost coverage");
  const dl = element("dl", { className: "metadata" });
  addDefinition(dl, "Coverage", cost.coverage); addDefinition(dl, "Attempts", cost.attempts);
  addDefinition(dl, "Expected attempts", cost.expected_attempts); addDefinition(dl, "Unaccounted attempts", cost.unaccounted_attempts);
  panel.append(dl, renderJson(cost.amounts));
  const issue = issuesBlock(cost.issues); if (issue) panel.append(issue);
  return panel;
}

function reportFloor(report: ReportDetail): unknown {
  return report.report.inference_floor ?? report.report.minimum_inference_n ?? report.report.inference_status ?? "Persisted report does not declare a floor";
}

function renderComparison(comparison: ComparisonView): HTMLElement {
  const article = element("article", { className: "comparison" });
  article.append(element("h3", { text: `${comparison.reference} → ${comparison.candidate}` }), element("p", { className: "badge", text: comparison.kind }));
  const categories = comparison.values.categories;
  const counts = comparison.values.counts ?? comparison.values.distribution;
  if (Array.isArray(categories) && counts && typeof counts === "object" && !Array.isArray(counts)) {
    const list = element("ol", { className: "ordinal" });
    for (const [category, count] of orderedCategories(categories.filter((v): v is string => typeof v === "string"), counts as Record<string, Json>)) {
      list.append(element("li", { text: `${category}: ${count ?? 0}` }));
    }
    article.append(list);
  } else article.append(renderJson(comparison.values));
  return article;
}

function showRecompute(panel: HTMLElement, result: RecomputeResult): void {
  const prior = panel.querySelector(".recompute-result"); if (prior) prior.remove();
  const resultNode = element("div", { className: `recompute-result status-${result.status}` });
  resultNode.append(element("strong", { text: result.status }), element("p", { text: result.reason ?? (result.matched ? "Stored and recomputed reports match." : "Stored and recomputed reports differ.") }));
  panel.append(resultNode);
}

function renderReport(root: HTMLElement, report: ReportDetail, source: DataSource): void {
  clearAndTitle(root, report.summary.metric, report.summary.report_ref);
  const layout = element("div", { className: "report-layout" });
  const results = section("Comparison results");
  results.append(element("p", { className: "inference-floor", text: `Descriptive only · persisted inference floor: ${String(reportFloor(report))}` }));
  if (!report.comparisons.length) results.append(element("p", { className: "empty-inline", text: "No comparisons are available." }));
  else report.comparisons.forEach((comparison) => results.append(renderComparison(comparison)));
  const context = element("div");
  const missing = section("Missingness"); missing.append(renderJson(report.missingness));
  const exclusions = section("Exclusions");
  if (!report.exclusions.length) exclusions.append(element("p", { text: "No exclusions." }));
  else for (const exclusion of report.exclusions) exclusions.append(element("p", { text: `${exclusion.subject_id} · ${exclusion.arm_id}: ${exclusion.classification} — ${exclusion.reason}` }));
  context.append(missing, exclusions, renderCost(report.costs)); layout.append(results, context); root.append(layout);
  const recompute = section("Recompute");
  if (!report.summary.recomputable) recompute.append(element("p", { className: "unavailable-inline", text: report.summary.recompute_disabled_reason ?? "Recompute is unavailable for this report." }));
  else {
    const button = element("button", { text: "Recompute report" }); button.type = "button";
    button.addEventListener("click", async () => {
      if (button.disabled) return;
      button.disabled = true; button.replaceChildren(); appendText(button, "Recomputing…");
      try { showRecompute(recompute, await source.recompute(report.summary.report_ref)); }
      catch (error) { showRecompute(recompute, { status: error instanceof DataUnavailable ? "unsupported" : "failed", matched: null, stored_digest: report.summary.report_ref, recomputed_digest: null, reason: error instanceof Error ? error.message : String(error) }); }
      finally { button.disabled = false; button.replaceChildren(); appendText(button, "Recompute report"); }
    });
    recompute.append(button);
  }
  root.append(recompute);
  const issue = issuesBlock(report.summary.issues); if (issue) root.append(issue);
}

async function renderRoute(root: HTMLElement, source: DataSource, route: Route): Promise<void> {
  if (route.kind === "unavailable") { statePage(root, "unavailable", `No view exists for ${route.path}.`); return; }
  statePage(root, "loading", "Loading review data…");
  try {
    if (route.kind === "browser") renderBrowser(root, await source.store());
    else if (route.kind === "run") renderGrid(root, await source.run(route.runKey));
    else if (route.kind === "cell") renderCell(root, await source.cell(route.runKey, route.cellId));
    else if (route.kind === "pair") renderPair(root, await source.pair(route.runKey, route.subjectId));
    else if (route.kind === "report") renderReport(root, await source.report(route.reportRef), source);
    else {
      const values = await source.ambiguities();
      clearAndTitle(root, "Display only", "Ambiguity queue");
      if (!values.length) { root.append(element("section", { className: "state panel state-empty", text: "No ambiguous evaluations." })); return; }
      const list = element("ul", { className: "ambiguity-list" });
      for (const value of values) {
        const item = element("li");
        item.append(localLink(`${value.evaluator_id} · ${value.coordinate_id}`, cellFragment(value.run_key, value.cell_id)));
        if (value.error_message) item.append(element("p", { className: "diagnostic", text: value.error_message }));
        list.append(item);
      }
      root.append(list);
    }
  } catch (error) {
    statePage(root, error instanceof DataUnavailable ? "unavailable" : "error", error instanceof Error ? error.message : String(error));
  }
}

export function start(doc: Document = document): void {
  const root = doc.querySelector<HTMLElement>("#app");
  if (!root) throw new Error("Missing #app root");
  let source: DataSource;
  try { source = dataSourceFromDocument(doc); }
  catch (error) { statePage(root, "error", error instanceof Error ? error.message : String(error)); return; }
  let generation = 0;
  const navigate = async () => {
    const current = ++generation;
    statePage(root, "loading", "Loading review data…");
    const staging = element("div");
    await renderRoute(staging, source, parseRoute(location.hash));
    if (current === generation) root.replaceChildren(...staging.childNodes);
  };
  window.addEventListener("hashchange", () => void navigate());
  void navigate();
}

if (typeof document !== "undefined") start();

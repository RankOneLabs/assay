import { start } from "./app";
import {
  DataUnavailable, exportDataFromDocument, type DataSource,
} from "./data";
import type {
  Ambiguity, CellDetail, ExportData, PairView, RecomputeResult, ReportDetail,
  RunDetail, StoreSummary,
} from "./types";

const encoded = (value: string): string => encodeURIComponent(value);

type EmbeddedPairView = Omit<PairView, "reference_cells" | "candidate_cells"> & {
  reference_cells: string[];
  candidate_cells: string[];
};

export class OfflineDataSource implements DataSource {
  readonly mode = "inline" as const;
  constructor(private readonly data: ExportData) {}

  private view<T>(path: string): T {
    const value = this.data.views[path];
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new DataUnavailable(`The offline export does not include ${path}.`);
    }
    return value as unknown as T;
  }

  async store(): Promise<StoreSummary> { return this.data.store; }
  async run(runKey: string): Promise<RunDetail> {
    return this.view(`/api/runs/${encoded(runKey)}`);
  }
  async cell(runKey: string, cellId: string): Promise<CellDetail> {
    return this.view(`/api/runs/${encoded(runKey)}/cells/${encoded(cellId)}`);
  }
  async pair(
    runKey: string, subjectId: string, reference: string, candidate: string,
  ): Promise<PairView> {
    const pair = this.view<EmbeddedPairView>(
      `/api/runs/${encoded(runKey)}/pairs/${encoded(subjectId)}`
      + `?reference=${encoded(reference)}&candidate=${encoded(candidate)}`,
    );
    return {
      ...pair,
      reference_cells: pair.reference_cells.map((path) => this.view<CellDetail>(path)),
      candidate_cells: pair.candidate_cells.map((path) => this.view<CellDetail>(path)),
    };
  }
  async report(reportRef: string): Promise<ReportDetail> {
    return this.view(`/api/reports/${encoded(reportRef)}`);
  }
  async ambiguities(): Promise<Ambiguity[]> {
    const value = this.data.views["/api/ambiguities"];
    if (!Array.isArray(value)) {
      throw new DataUnavailable("The ambiguity queue was not included in the offline export.");
    }
    return value as unknown as Ambiguity[];
  }
  async recompute(_reportRef: string): Promise<RecomputeResult> {
    throw new DataUnavailable("Recompute requires the local Assay server.");
  }
}

if (typeof document !== "undefined") {
  try {
    const data = exportDataFromDocument(document);
    if (data === null) throw new Error("Missing offline export data");
    start(document, new OfflineDataSource(data));
  } catch (error) {
    const root = document.querySelector("#app");
    if (root) {
      const panel = document.createElement("section");
      panel.className = "state panel state-error";
      panel.setAttribute("role", "alert");
      panel.append(document.createTextNode(error instanceof Error ? error.message : String(error)));
      root.replaceChildren(panel);
    }
  }
}

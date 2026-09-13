import type {
  Ambiguity, CellDetail, ExportData, PairView, RecomputeResult, ReportDetail, RunDetail, StoreSummary,
} from "./types";

export class DataUnavailable extends Error {}

export interface DataSource {
  readonly mode: "inline" | "http";
  store(): Promise<StoreSummary>;
  run(runKey: string): Promise<RunDetail>;
  cell(runKey: string, cellId: string): Promise<CellDetail>;
  pair(runKey: string, subjectId: string): Promise<PairView>;
  report(reportRef: string): Promise<ReportDetail>;
  ambiguities(): Promise<Ambiguity[]>;
  recompute(reportRef: string): Promise<RecomputeResult>;
}

function objectValue(value: unknown, context: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`Malformed ${context}`);
  return value as Record<string, unknown>;
}

function encoded(value: string): string { return encodeURIComponent(value); }

export class InlineDataSource implements DataSource {
  readonly mode = "inline" as const;
  constructor(private readonly data: ExportData) {}

  async store(): Promise<StoreSummary> { return this.data.store; }

  private view<T>(names: string[]): T {
    for (const name of names) {
      const value = this.data.views[name];
      if (value !== undefined) return objectValue(value, `inline view ${name}`) as T;
    }
    throw new DataUnavailable("This view was not included in the offline export.");
  }

  async run(runKey: string): Promise<RunDetail> {
    return this.view([`#/runs/${encoded(runKey)}`, `/runs/${encoded(runKey)}`, `run:${runKey}`, runKey]);
  }
  async cell(runKey: string, cellId: string): Promise<CellDetail> {
    return this.view([
      `#/runs/${encoded(runKey)}/cells/${encoded(cellId)}`,
      `/runs/${encoded(runKey)}/cells/${encoded(cellId)}`,
      `cell:${runKey}:${cellId}`,
    ]);
  }
  async pair(runKey: string, subjectId: string): Promise<PairView> {
    return this.view([
      `#/runs/${encoded(runKey)}/pairs/${encoded(subjectId)}`,
      `/runs/${encoded(runKey)}/pairs/${encoded(subjectId)}`,
      `pair:${runKey}:${subjectId}`,
    ]);
  }
  async report(reportRef: string): Promise<ReportDetail> {
    return this.view([`#/reports/${encoded(reportRef)}`, `/reports/${encoded(reportRef)}`, `report:${reportRef}`, reportRef]);
  }
  async ambiguities(): Promise<Ambiguity[]> {
    const value = this.data.views["#/ambiguities"] ?? this.data.views["/ambiguities"] ?? this.data.views.ambiguities;
    if (value === undefined) throw new DataUnavailable("The ambiguity queue was not included in the offline export.");
    if (!Array.isArray(value)) throw new Error("Malformed inline ambiguity queue");
    return value as unknown as Ambiguity[];
  }
  async recompute(_reportRef: string): Promise<RecomputeResult> {
    throw new DataUnavailable("Recompute is unavailable in an offline export.");
  }
}

export class HttpDataSource implements DataSource {
  readonly mode = "http" as const;
  constructor(private readonly base = "") {}

  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(this.base + path, { ...init, headers: { Accept: "application/json", ...init?.headers } });
    if (response.status === 404 || response.status === 405 || response.status === 501) {
      throw new DataUnavailable(`The server does not provide this view (${response.status}).`);
    }
    if (!response.ok) throw new Error(`Request failed (${response.status} ${response.statusText})`);
    return objectValue(await response.json(), `response from ${path}`) as T;
  }

  store(): Promise<StoreSummary> { return this.request("/api/store"); }
  run(runKey: string): Promise<RunDetail> { return this.request(`/api/runs/${encoded(runKey)}`); }
  cell(runKey: string, cellId: string): Promise<CellDetail> {
    return this.request(`/api/runs/${encoded(runKey)}/cells/${encoded(cellId)}`);
  }
  pair(runKey: string, subjectId: string): Promise<PairView> {
    return this.request(`/api/runs/${encoded(runKey)}/pairs/${encoded(subjectId)}`);
  }
  report(reportRef: string): Promise<ReportDetail> { return this.request(`/api/reports/${encoded(reportRef)}`); }
  async ambiguities(): Promise<Ambiguity[]> {
    const response = await fetch(this.base + "/api/ambiguities", { headers: { Accept: "application/json" } });
    if (response.status === 404 || response.status === 405 || response.status === 501) throw new DataUnavailable("The server does not provide the ambiguity queue.");
    if (!response.ok) throw new Error(`Request failed (${response.status} ${response.statusText})`);
    const value: unknown = await response.json();
    if (!Array.isArray(value)) throw new Error("Malformed ambiguity response");
    return value as Ambiguity[];
  }
  recompute(reportRef: string): Promise<RecomputeResult> {
    return this.request(`/api/reports/${encoded(reportRef)}/recompute`, { method: "POST" });
  }
}

export function dataSourceFromDocument(doc: Document = document): DataSource {
  const node = doc.querySelector<HTMLScriptElement>(
    'script[type="application/json"][data-assay-review], script#assay-review-data[type="application/json"]',
  );
  if (!node) return new HttpDataSource();
  let parsed: unknown;
  try { parsed = JSON.parse(node.textContent ?? ""); } catch (error) {
    throw new Error(`Malformed inline review data: ${error instanceof Error ? error.message : String(error)}`);
  }
  const data = objectValue(parsed, "inline review data");
  if (data.schema_version !== "assay-review-export/0.1.0" || !data.store || !data.views) {
    throw new Error("Malformed inline review data: unsupported schema or missing store/views");
  }
  return new InlineDataSource(data as unknown as ExportData);
}

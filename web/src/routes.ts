export type Route =
  | { kind: "browser" }
  | { kind: "ambiguities" }
  | { kind: "run"; runKey: string }
  | { kind: "cell"; runKey: string; cellId: string }
  | { kind: "pair"; runKey: string; subjectId: string; reference: string; candidate: string }
  | { kind: "report"; reportRef: string }
  | { kind: "unavailable"; path: string };

const decode = (part: string): string | null => {
  try { return decodeURIComponent(part); } catch { return null; }
};

export function parseRoute(hash: string): Route {
  const path = hash.startsWith("#") ? hash.slice(1) : hash;
  if (path === "" || path === "/") return { kind: "browser" };
  if (path === "/ambiguities") return { kind: "ambiguities" };
  if (path.startsWith("/reports/")) {
    const reportRef = decode(path.slice(9));
    return reportRef ? { kind: "report", reportRef } : { kind: "unavailable", path };
  }
  if (path.startsWith("/runs/")) {
    const rest = path.slice(6);
    const cellAt = rest.lastIndexOf("/cells/");
    const pairAt = rest.lastIndexOf("/pairs/");
    if (cellAt > 0) {
      const runKey = decode(rest.slice(0, cellAt));
      const cellId = decode(rest.slice(cellAt + 7));
      if (runKey && cellId) return { kind: "cell", runKey, cellId };
    } else if (pairAt > 0) {
      const runKey = decode(rest.slice(0, pairAt));
      const pairRoute = rest.slice(pairAt + 7);
      const queryAt = pairRoute.indexOf("?");
      const subjectId = decode(queryAt < 0 ? pairRoute : pairRoute.slice(0, queryAt));
      const query = new URLSearchParams(queryAt < 0 ? "" : pairRoute.slice(queryAt + 1));
      const reference = query.get("reference");
      const candidate = query.get("candidate");
      if (runKey && subjectId && reference && candidate) {
        return { kind: "pair", runKey, subjectId, reference, candidate };
      }
    } else {
      const runKey = decode(rest);
      if (runKey) return { kind: "run", runKey };
    }
  }
  return { kind: "unavailable", path };
}

const encoded = (value: string) => encodeURIComponent(value);
export function defaultPair(arms: readonly string[]): { reference: string; candidate: string } | null {
  if (arms.length < 2) return null;
  const reference = arms.find((arm) => arm === "reference" || arm === "clean") ?? arms[0]!;
  const candidate = arms.find(
    (arm) => arm !== reference && (arm === "candidate" || arm === "inconsistent"),
  ) ?? arms.find((arm) => arm !== reference)!;
  return { reference, candidate };
}
export const runFragment = (runKey: string) => `#/runs/${encoded(runKey)}`;
export const cellFragment = (runKey: string, cellId: string) => `${runFragment(runKey)}/cells/${encoded(cellId)}`;
export const pairFragment = (runKey: string, subjectId: string, reference: string, candidate: string) =>
  `${runFragment(runKey)}/pairs/${encoded(subjectId)}?reference=${encoded(reference)}&candidate=${encoded(candidate)}`;
export const reportFragment = (reportRef: string) => `#/reports/${encoded(reportRef)}`;

export type Route =
  | { kind: "browser" }
  | { kind: "ambiguities" }
  | { kind: "run"; runKey: string }
  | { kind: "cell"; runKey: string; cellId: string }
  | { kind: "pair"; runKey: string; subjectId: string }
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
      const subjectId = decode(rest.slice(pairAt + 7));
      if (runKey && subjectId) return { kind: "pair", runKey, subjectId };
    } else {
      const runKey = decode(rest);
      if (runKey) return { kind: "run", runKey };
    }
  }
  return { kind: "unavailable", path };
}

const encoded = (value: string) => encodeURIComponent(value);
export const runFragment = (runKey: string) => `#/runs/${encoded(runKey)}`;
export const cellFragment = (runKey: string, cellId: string) => `${runFragment(runKey)}/cells/${encoded(cellId)}`;
export const pairFragment = (runKey: string, subjectId: string) => `${runFragment(runKey)}/pairs/${encoded(subjectId)}`;
export const reportFragment = (reportRef: string) => `#/reports/${encoded(reportRef)}`;

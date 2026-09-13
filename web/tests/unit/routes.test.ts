import { describe, expect, test } from "bun:test";
import {
  cellFragment, defaultPair, pairFragment, parseRoute, reportFragment,
} from "../../src/routes";

describe("fragment routes", () => {
  test("keeps a loose full run key before a cell id", () => {
    const route = parseRoute("#/runs/run%2Fregion%3Aalpha/cells/cell%2Fone");
    expect(route).toEqual({ kind: "cell", runKey: "run/region:alpha", cellId: "cell/one" });
  });

  test("round trips generated document-local links", () => {
    expect(parseRoute(cellFragment("one/two", "a:b"))).toEqual({ kind: "cell", runKey: "one/two", cellId: "a:b" });
    expect(parseRoute(pairFragment("one/two", "subject", "baseline", "treatment"))).toEqual({
      kind: "pair", runKey: "one/two", subjectId: "subject", reference: "baseline", candidate: "treatment",
    });
    expect(parseRoute(reportFragment("sha256:abc"))).toEqual({ kind: "report", reportRef: "sha256:abc" });
  });

  test("rejects malformed and unknown fragments locally", () => {
    expect(parseRoute("#/runs/%GG").kind).toBe("unavailable");
    expect(parseRoute("#/external/https://example.test").kind).toBe("unavailable");
  });

  test("chooses semantic arms before declared-order fallback", () => {
    expect(defaultPair(["candidate", "reference"])).toEqual({
      reference: "reference", candidate: "candidate",
    });
    expect(defaultPair(["baseline", "treatment"])).toEqual({
      reference: "baseline", candidate: "treatment",
    });
  });
});

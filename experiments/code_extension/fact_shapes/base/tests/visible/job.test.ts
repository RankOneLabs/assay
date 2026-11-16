import { describe, expect, test } from "bun:test";
import { parseJob, patchJob, serializeJob, equalJob } from "../../src/payloads/job.ts";

describe("job payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseJob({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseJob({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseJob({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseJob({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("requester accepts a normalized value", () => {
    const result = parseJob({ requester: "value" });
    expect(result.requester).toBe("value");
  });

  test("requester trims surrounding whitespace", () => {
    const result = parseJob({ requester: "  value  " });
    expect(result.requester).toBe("value");
  });

  test("requester rejects empty text", () => {
    const input = { requester: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("requester rejects nontext input", () => {
    const input = { requester: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("requester accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ requester: text }).requester).toBe(text);
  });

  test("requester rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ requester: text })).toThrow();
  });

  test("requester leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "requester")).toBe(false);
  });

  test("projectKey accepts a normalized value", () => {
    const result = parseJob({ projectKey: "value" });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey trims surrounding whitespace", () => {
    const result = parseJob({ projectKey: "  value  " });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey rejects empty text", () => {
    const input = { projectKey: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("projectKey rejects nontext input", () => {
    const input = { projectKey: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("projectKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ projectKey: text }).projectKey).toBe(text);
  });

  test("projectKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ projectKey: text })).toThrow();
  });

  test("projectKey leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "projectKey")).toBe(false);
  });

  test("queueKey accepts a normalized value", () => {
    const result = parseJob({ queueKey: "value" });
    expect(result.queueKey).toBe("value");
  });

  test("queueKey trims surrounding whitespace", () => {
    const result = parseJob({ queueKey: "  value  " });
    expect(result.queueKey).toBe("value");
  });

  test("queueKey rejects empty text", () => {
    const input = { queueKey: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("queueKey rejects nontext input", () => {
    const input = { queueKey: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("queueKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ queueKey: text }).queueKey).toBe(text);
  });

  test("queueKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ queueKey: text })).toThrow();
  });

  test("queueKey leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "queueKey")).toBe(false);
  });

  test("workerHint accepts a normalized value", () => {
    const result = parseJob({ workerHint: "value" });
    expect(result.workerHint).toBe("value");
  });

  test("workerHint trims surrounding whitespace", () => {
    const result = parseJob({ workerHint: "  value  " });
    expect(result.workerHint).toBe("value");
  });

  test("workerHint rejects empty text", () => {
    const input = { workerHint: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("workerHint rejects nontext input", () => {
    const input = { workerHint: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("workerHint accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ workerHint: text }).workerHint).toBe(text);
  });

  test("workerHint rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ workerHint: text })).toThrow();
  });

  test("workerHint leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "workerHint")).toBe(false);
  });

  test("inputDigest accepts a normalized value", () => {
    const result = parseJob({ inputDigest: "value" });
    expect(result.inputDigest).toBe("value");
  });

  test("inputDigest trims surrounding whitespace", () => {
    const result = parseJob({ inputDigest: "  value  " });
    expect(result.inputDigest).toBe("value");
  });

  test("inputDigest rejects empty text", () => {
    const input = { inputDigest: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("inputDigest rejects nontext input", () => {
    const input = { inputDigest: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("inputDigest accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ inputDigest: text }).inputDigest).toBe(text);
  });

  test("inputDigest rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ inputDigest: text })).toThrow();
  });

  test("inputDigest leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "inputDigest")).toBe(false);
  });

  test("outputPrefix accepts a normalized value", () => {
    const result = parseJob({ outputPrefix: "value" });
    expect(result.outputPrefix).toBe("value");
  });

  test("outputPrefix trims surrounding whitespace", () => {
    const result = parseJob({ outputPrefix: "  value  " });
    expect(result.outputPrefix).toBe("value");
  });

  test("outputPrefix rejects empty text", () => {
    const input = { outputPrefix: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("outputPrefix rejects nontext input", () => {
    const input = { outputPrefix: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("outputPrefix accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ outputPrefix: text }).outputPrefix).toBe(text);
  });

  test("outputPrefix rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ outputPrefix: text })).toThrow();
  });

  test("outputPrefix leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "outputPrefix")).toBe(false);
  });

  test("correlationKey accepts a normalized value", () => {
    const result = parseJob({ correlationKey: "value" });
    expect(result.correlationKey).toBe("value");
  });

  test("correlationKey trims surrounding whitespace", () => {
    const result = parseJob({ correlationKey: "  value  " });
    expect(result.correlationKey).toBe("value");
  });

  test("correlationKey rejects empty text", () => {
    const input = { correlationKey: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("correlationKey rejects nontext input", () => {
    const input = { correlationKey: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("correlationKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ correlationKey: text }).correlationKey).toBe(text);
  });

  test("correlationKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ correlationKey: text })).toThrow();
  });

  test("correlationKey leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "correlationKey")).toBe(false);
  });

  test("deduplicationKey accepts a normalized value", () => {
    const result = parseJob({ deduplicationKey: "value" });
    expect(result.deduplicationKey).toBe("value");
  });

  test("deduplicationKey trims surrounding whitespace", () => {
    const result = parseJob({ deduplicationKey: "  value  " });
    expect(result.deduplicationKey).toBe("value");
  });

  test("deduplicationKey rejects empty text", () => {
    const input = { deduplicationKey: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("deduplicationKey rejects nontext input", () => {
    const input = { deduplicationKey: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("deduplicationKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ deduplicationKey: text }).deduplicationKey).toBe(text);
  });

  test("deduplicationKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ deduplicationKey: text })).toThrow();
  });

  test("deduplicationKey leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "deduplicationKey")).toBe(false);
  });

  test("traceKey accepts a normalized value", () => {
    const result = parseJob({ traceKey: "value" });
    expect(result.traceKey).toBe("value");
  });

  test("traceKey trims surrounding whitespace", () => {
    const result = parseJob({ traceKey: "  value  " });
    expect(result.traceKey).toBe("value");
  });

  test("traceKey rejects empty text", () => {
    const input = { traceKey: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("traceKey rejects nontext input", () => {
    const input = { traceKey: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("traceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ traceKey: text }).traceKey).toBe(text);
  });

  test("traceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ traceKey: text })).toThrow();
  });

  test("traceKey leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "traceKey")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseJob({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseJob({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseJob(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseJob(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseJob({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseJob({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseJob({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseJob({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseJob(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseJob({ title: "before", description: "keep" });
    const changed = patchJob(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeJob(left)).toBe(serializeJob(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalJob({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalJob({ title: "a" }, { title: "b" })).toBe(false);
  });
});

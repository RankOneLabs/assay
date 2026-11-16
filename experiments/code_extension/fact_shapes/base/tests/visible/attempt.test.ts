import { describe, expect, test } from "bun:test";
import { parseAttempt, patchAttempt, serializeAttempt, equalAttempt } from "../../src/payloads/attempt.ts";

describe("attempt payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseAttempt({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseAttempt({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseAttempt({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseAttempt({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("jobKey accepts a normalized value", () => {
    const result = parseAttempt({ jobKey: "value" });
    expect(result.jobKey).toBe("value");
  });

  test("jobKey trims surrounding whitespace", () => {
    const result = parseAttempt({ jobKey: "  value  " });
    expect(result.jobKey).toBe("value");
  });

  test("jobKey rejects empty text", () => {
    const input = { jobKey: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("jobKey rejects nontext input", () => {
    const input = { jobKey: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("jobKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ jobKey: text }).jobKey).toBe(text);
  });

  test("jobKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ jobKey: text })).toThrow();
  });

  test("jobKey leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "jobKey")).toBe(false);
  });

  test("workerKey accepts a normalized value", () => {
    const result = parseAttempt({ workerKey: "value" });
    expect(result.workerKey).toBe("value");
  });

  test("workerKey trims surrounding whitespace", () => {
    const result = parseAttempt({ workerKey: "  value  " });
    expect(result.workerKey).toBe("value");
  });

  test("workerKey rejects empty text", () => {
    const input = { workerKey: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("workerKey rejects nontext input", () => {
    const input = { workerKey: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("workerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ workerKey: text }).workerKey).toBe(text);
  });

  test("workerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ workerKey: text })).toThrow();
  });

  test("workerKey leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "workerKey")).toBe(false);
  });

  test("inputKey accepts a normalized value", () => {
    const result = parseAttempt({ inputKey: "value" });
    expect(result.inputKey).toBe("value");
  });

  test("inputKey trims surrounding whitespace", () => {
    const result = parseAttempt({ inputKey: "  value  " });
    expect(result.inputKey).toBe("value");
  });

  test("inputKey rejects empty text", () => {
    const input = { inputKey: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("inputKey rejects nontext input", () => {
    const input = { inputKey: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("inputKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ inputKey: text }).inputKey).toBe(text);
  });

  test("inputKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ inputKey: text })).toThrow();
  });

  test("inputKey leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "inputKey")).toBe(false);
  });

  test("outputKey accepts a normalized value", () => {
    const result = parseAttempt({ outputKey: "value" });
    expect(result.outputKey).toBe("value");
  });

  test("outputKey trims surrounding whitespace", () => {
    const result = parseAttempt({ outputKey: "  value  " });
    expect(result.outputKey).toBe("value");
  });

  test("outputKey rejects empty text", () => {
    const input = { outputKey: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("outputKey rejects nontext input", () => {
    const input = { outputKey: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("outputKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ outputKey: text }).outputKey).toBe(text);
  });

  test("outputKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ outputKey: text })).toThrow();
  });

  test("outputKey leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "outputKey")).toBe(false);
  });

  test("traceKey accepts a normalized value", () => {
    const result = parseAttempt({ traceKey: "value" });
    expect(result.traceKey).toBe("value");
  });

  test("traceKey trims surrounding whitespace", () => {
    const result = parseAttempt({ traceKey: "  value  " });
    expect(result.traceKey).toBe("value");
  });

  test("traceKey rejects empty text", () => {
    const input = { traceKey: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("traceKey rejects nontext input", () => {
    const input = { traceKey: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("traceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ traceKey: text }).traceKey).toBe(text);
  });

  test("traceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ traceKey: text })).toThrow();
  });

  test("traceKey leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "traceKey")).toBe(false);
  });

  test("errorCode accepts a normalized value", () => {
    const result = parseAttempt({ errorCode: "value" });
    expect(result.errorCode).toBe("value");
  });

  test("errorCode trims surrounding whitespace", () => {
    const result = parseAttempt({ errorCode: "  value  " });
    expect(result.errorCode).toBe("value");
  });

  test("errorCode rejects empty text", () => {
    const input = { errorCode: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("errorCode rejects nontext input", () => {
    const input = { errorCode: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("errorCode accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ errorCode: text }).errorCode).toBe(text);
  });

  test("errorCode rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ errorCode: text })).toThrow();
  });

  test("errorCode leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "errorCode")).toBe(false);
  });

  test("errorMessage accepts a normalized value", () => {
    const result = parseAttempt({ errorMessage: "value" });
    expect(result.errorMessage).toBe("value");
  });

  test("errorMessage trims surrounding whitespace", () => {
    const result = parseAttempt({ errorMessage: "  value  " });
    expect(result.errorMessage).toBe("value");
  });

  test("errorMessage rejects empty text", () => {
    const input = { errorMessage: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("errorMessage rejects nontext input", () => {
    const input = { errorMessage: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("errorMessage accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ errorMessage: text }).errorMessage).toBe(text);
  });

  test("errorMessage rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ errorMessage: text })).toThrow();
  });

  test("errorMessage leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "errorMessage")).toBe(false);
  });

  test("runtime accepts a normalized value", () => {
    const result = parseAttempt({ runtime: "value" });
    expect(result.runtime).toBe("value");
  });

  test("runtime trims surrounding whitespace", () => {
    const result = parseAttempt({ runtime: "  value  " });
    expect(result.runtime).toBe("value");
  });

  test("runtime rejects empty text", () => {
    const input = { runtime: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("runtime rejects nontext input", () => {
    const input = { runtime: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("runtime accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ runtime: text }).runtime).toBe(text);
  });

  test("runtime rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ runtime: text })).toThrow();
  });

  test("runtime leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "runtime")).toBe(false);
  });

  test("revision accepts a normalized value", () => {
    const result = parseAttempt({ revision: "value" });
    expect(result.revision).toBe("value");
  });

  test("revision trims surrounding whitespace", () => {
    const result = parseAttempt({ revision: "  value  " });
    expect(result.revision).toBe("value");
  });

  test("revision rejects empty text", () => {
    const input = { revision: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("revision rejects nontext input", () => {
    const input = { revision: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("revision accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ revision: text }).revision).toBe(text);
  });

  test("revision rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ revision: text })).toThrow();
  });

  test("revision leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "revision")).toBe(false);
  });

  test("checkpointKey accepts a normalized value", () => {
    const result = parseAttempt({ checkpointKey: "value" });
    expect(result.checkpointKey).toBe("value");
  });

  test("checkpointKey trims surrounding whitespace", () => {
    const result = parseAttempt({ checkpointKey: "  value  " });
    expect(result.checkpointKey).toBe("value");
  });

  test("checkpointKey rejects empty text", () => {
    const input = { checkpointKey: "   " };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("checkpointKey rejects nontext input", () => {
    const input = { checkpointKey: 42 };
    expect(() => parseAttempt(input)).toThrow();
  });

  test("checkpointKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttempt({ checkpointKey: text }).checkpointKey).toBe(text);
  });

  test("checkpointKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttempt({ checkpointKey: text })).toThrow();
  });

  test("checkpointKey leaves omitted values absent", () => {
    const result = parseAttempt({});
    expect(Object.hasOwn(result, "checkpointKey")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseAttempt({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseAttempt(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseAttempt({ title: "before", description: "keep" });
    const changed = patchAttempt(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeAttempt(left)).toBe(serializeAttempt(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalAttempt({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalAttempt({ title: "a" }, { title: "b" })).toBe(false);
  });
});

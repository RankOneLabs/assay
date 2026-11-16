import { describe, expect, test } from "bun:test";
import { parseCheckpoint, patchCheckpoint, serializeCheckpoint, equalCheckpoint } from "../../src/payloads/checkpoint.ts";

describe("checkpoint payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseCheckpoint({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseCheckpoint({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseCheckpoint({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseCheckpoint({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("jobKey accepts a normalized value", () => {
    const result = parseCheckpoint({ jobKey: "value" });
    expect(result.jobKey).toBe("value");
  });

  test("jobKey trims surrounding whitespace", () => {
    const result = parseCheckpoint({ jobKey: "  value  " });
    expect(result.jobKey).toBe("value");
  });

  test("jobKey rejects empty text", () => {
    const input = { jobKey: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("jobKey rejects nontext input", () => {
    const input = { jobKey: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("jobKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ jobKey: text }).jobKey).toBe(text);
  });

  test("jobKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ jobKey: text })).toThrow();
  });

  test("jobKey leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "jobKey")).toBe(false);
  });

  test("attemptKey accepts a normalized value", () => {
    const result = parseCheckpoint({ attemptKey: "value" });
    expect(result.attemptKey).toBe("value");
  });

  test("attemptKey trims surrounding whitespace", () => {
    const result = parseCheckpoint({ attemptKey: "  value  " });
    expect(result.attemptKey).toBe("value");
  });

  test("attemptKey rejects empty text", () => {
    const input = { attemptKey: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("attemptKey rejects nontext input", () => {
    const input = { attemptKey: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("attemptKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ attemptKey: text }).attemptKey).toBe(text);
  });

  test("attemptKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ attemptKey: text })).toThrow();
  });

  test("attemptKey leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "attemptKey")).toBe(false);
  });

  test("storageKey accepts a normalized value", () => {
    const result = parseCheckpoint({ storageKey: "value" });
    expect(result.storageKey).toBe("value");
  });

  test("storageKey trims surrounding whitespace", () => {
    const result = parseCheckpoint({ storageKey: "  value  " });
    expect(result.storageKey).toBe("value");
  });

  test("storageKey rejects empty text", () => {
    const input = { storageKey: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("storageKey rejects nontext input", () => {
    const input = { storageKey: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("storageKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ storageKey: text }).storageKey).toBe(text);
  });

  test("storageKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ storageKey: text })).toThrow();
  });

  test("storageKey leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "storageKey")).toBe(false);
  });

  test("checksum accepts a normalized value", () => {
    const result = parseCheckpoint({ checksum: "value" });
    expect(result.checksum).toBe("value");
  });

  test("checksum trims surrounding whitespace", () => {
    const result = parseCheckpoint({ checksum: "  value  " });
    expect(result.checksum).toBe("value");
  });

  test("checksum rejects empty text", () => {
    const input = { checksum: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("checksum rejects nontext input", () => {
    const input = { checksum: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("checksum accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ checksum: text }).checksum).toBe(text);
  });

  test("checksum rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ checksum: text })).toThrow();
  });

  test("checksum leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "checksum")).toBe(false);
  });

  test("format accepts a normalized value", () => {
    const result = parseCheckpoint({ format: "value" });
    expect(result.format).toBe("value");
  });

  test("format trims surrounding whitespace", () => {
    const result = parseCheckpoint({ format: "  value  " });
    expect(result.format).toBe("value");
  });

  test("format rejects empty text", () => {
    const input = { format: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("format rejects nontext input", () => {
    const input = { format: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("format accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ format: text }).format).toBe(text);
  });

  test("format rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ format: text })).toThrow();
  });

  test("format leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "format")).toBe(false);
  });

  test("version accepts a normalized value", () => {
    const result = parseCheckpoint({ version: "value" });
    expect(result.version).toBe("value");
  });

  test("version trims surrounding whitespace", () => {
    const result = parseCheckpoint({ version: "  value  " });
    expect(result.version).toBe("value");
  });

  test("version rejects empty text", () => {
    const input = { version: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("version rejects nontext input", () => {
    const input = { version: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("version accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ version: text }).version).toBe(text);
  });

  test("version rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ version: text })).toThrow();
  });

  test("version leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "version")).toBe(false);
  });

  test("producer accepts a normalized value", () => {
    const result = parseCheckpoint({ producer: "value" });
    expect(result.producer).toBe("value");
  });

  test("producer trims surrounding whitespace", () => {
    const result = parseCheckpoint({ producer: "  value  " });
    expect(result.producer).toBe("value");
  });

  test("producer rejects empty text", () => {
    const input = { producer: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("producer rejects nontext input", () => {
    const input = { producer: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("producer accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ producer: text }).producer).toBe(text);
  });

  test("producer rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ producer: text })).toThrow();
  });

  test("producer leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "producer")).toBe(false);
  });

  test("resumeToken accepts a normalized value", () => {
    const result = parseCheckpoint({ resumeToken: "value" });
    expect(result.resumeToken).toBe("value");
  });

  test("resumeToken trims surrounding whitespace", () => {
    const result = parseCheckpoint({ resumeToken: "  value  " });
    expect(result.resumeToken).toBe("value");
  });

  test("resumeToken rejects empty text", () => {
    const input = { resumeToken: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("resumeToken rejects nontext input", () => {
    const input = { resumeToken: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("resumeToken accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ resumeToken: text }).resumeToken).toBe(text);
  });

  test("resumeToken rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ resumeToken: text })).toThrow();
  });

  test("resumeToken leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "resumeToken")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseCheckpoint({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseCheckpoint({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("encryptionKey accepts a normalized value", () => {
    const result = parseCheckpoint({ encryptionKey: "value" });
    expect(result.encryptionKey).toBe("value");
  });

  test("encryptionKey trims surrounding whitespace", () => {
    const result = parseCheckpoint({ encryptionKey: "  value  " });
    expect(result.encryptionKey).toBe("value");
  });

  test("encryptionKey rejects empty text", () => {
    const input = { encryptionKey: "   " };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("encryptionKey rejects nontext input", () => {
    const input = { encryptionKey: 42 };
    expect(() => parseCheckpoint(input)).toThrow();
  });

  test("encryptionKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCheckpoint({ encryptionKey: text }).encryptionKey).toBe(text);
  });

  test("encryptionKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCheckpoint({ encryptionKey: text })).toThrow();
  });

  test("encryptionKey leaves omitted values absent", () => {
    const result = parseCheckpoint({});
    expect(Object.hasOwn(result, "encryptionKey")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseCheckpoint({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseCheckpoint(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseCheckpoint({ title: "before", description: "keep" });
    const changed = patchCheckpoint(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeCheckpoint(left)).toBe(serializeCheckpoint(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalCheckpoint({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalCheckpoint({ title: "a" }, { title: "b" })).toBe(false);
  });
});

import { describe, expect, test } from "bun:test";
import { parseArtifact, patchArtifact, serializeArtifact, equalArtifact } from "../../src/payloads/artifact.ts";

describe("artifact payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseArtifact({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseArtifact({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseArtifact({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseArtifact({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("jobKey accepts a normalized value", () => {
    const result = parseArtifact({ jobKey: "value" });
    expect(result.jobKey).toBe("value");
  });

  test("jobKey trims surrounding whitespace", () => {
    const result = parseArtifact({ jobKey: "  value  " });
    expect(result.jobKey).toBe("value");
  });

  test("jobKey rejects empty text", () => {
    const input = { jobKey: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("jobKey rejects nontext input", () => {
    const input = { jobKey: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("jobKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ jobKey: text }).jobKey).toBe(text);
  });

  test("jobKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ jobKey: text })).toThrow();
  });

  test("jobKey leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "jobKey")).toBe(false);
  });

  test("storageKey accepts a normalized value", () => {
    const result = parseArtifact({ storageKey: "value" });
    expect(result.storageKey).toBe("value");
  });

  test("storageKey trims surrounding whitespace", () => {
    const result = parseArtifact({ storageKey: "  value  " });
    expect(result.storageKey).toBe("value");
  });

  test("storageKey rejects empty text", () => {
    const input = { storageKey: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("storageKey rejects nontext input", () => {
    const input = { storageKey: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("storageKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ storageKey: text }).storageKey).toBe(text);
  });

  test("storageKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ storageKey: text })).toThrow();
  });

  test("storageKey leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "storageKey")).toBe(false);
  });

  test("mediaType accepts a normalized value", () => {
    const result = parseArtifact({ mediaType: "value" });
    expect(result.mediaType).toBe("value");
  });

  test("mediaType trims surrounding whitespace", () => {
    const result = parseArtifact({ mediaType: "  value  " });
    expect(result.mediaType).toBe("value");
  });

  test("mediaType rejects empty text", () => {
    const input = { mediaType: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("mediaType rejects nontext input", () => {
    const input = { mediaType: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("mediaType accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ mediaType: text }).mediaType).toBe(text);
  });

  test("mediaType rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ mediaType: text })).toThrow();
  });

  test("mediaType leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "mediaType")).toBe(false);
  });

  test("checksum accepts a normalized value", () => {
    const result = parseArtifact({ checksum: "value" });
    expect(result.checksum).toBe("value");
  });

  test("checksum trims surrounding whitespace", () => {
    const result = parseArtifact({ checksum: "  value  " });
    expect(result.checksum).toBe("value");
  });

  test("checksum rejects empty text", () => {
    const input = { checksum: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("checksum rejects nontext input", () => {
    const input = { checksum: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("checksum accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ checksum: text }).checksum).toBe(text);
  });

  test("checksum rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ checksum: text })).toThrow();
  });

  test("checksum leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "checksum")).toBe(false);
  });

  test("filename accepts a normalized value", () => {
    const result = parseArtifact({ filename: "value" });
    expect(result.filename).toBe("value");
  });

  test("filename trims surrounding whitespace", () => {
    const result = parseArtifact({ filename: "  value  " });
    expect(result.filename).toBe("value");
  });

  test("filename rejects empty text", () => {
    const input = { filename: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("filename rejects nontext input", () => {
    const input = { filename: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("filename accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ filename: text }).filename).toBe(text);
  });

  test("filename rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ filename: text })).toThrow();
  });

  test("filename leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "filename")).toBe(false);
  });

  test("encoding accepts a normalized value", () => {
    const result = parseArtifact({ encoding: "value" });
    expect(result.encoding).toBe("value");
  });

  test("encoding trims surrounding whitespace", () => {
    const result = parseArtifact({ encoding: "  value  " });
    expect(result.encoding).toBe("value");
  });

  test("encoding rejects empty text", () => {
    const input = { encoding: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("encoding rejects nontext input", () => {
    const input = { encoding: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("encoding accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ encoding: text }).encoding).toBe(text);
  });

  test("encoding rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ encoding: text })).toThrow();
  });

  test("encoding leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "encoding")).toBe(false);
  });

  test("producer accepts a normalized value", () => {
    const result = parseArtifact({ producer: "value" });
    expect(result.producer).toBe("value");
  });

  test("producer trims surrounding whitespace", () => {
    const result = parseArtifact({ producer: "  value  " });
    expect(result.producer).toBe("value");
  });

  test("producer rejects empty text", () => {
    const input = { producer: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("producer rejects nontext input", () => {
    const input = { producer: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("producer accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ producer: text }).producer).toBe(text);
  });

  test("producer rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ producer: text })).toThrow();
  });

  test("producer leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "producer")).toBe(false);
  });

  test("collection accepts a normalized value", () => {
    const result = parseArtifact({ collection: "value" });
    expect(result.collection).toBe("value");
  });

  test("collection trims surrounding whitespace", () => {
    const result = parseArtifact({ collection: "  value  " });
    expect(result.collection).toBe("value");
  });

  test("collection rejects empty text", () => {
    const input = { collection: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("collection rejects nontext input", () => {
    const input = { collection: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("collection accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ collection: text }).collection).toBe(text);
  });

  test("collection rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ collection: text })).toThrow();
  });

  test("collection leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "collection")).toBe(false);
  });

  test("retention accepts a normalized value", () => {
    const result = parseArtifact({ retention: "value" });
    expect(result.retention).toBe("value");
  });

  test("retention trims surrounding whitespace", () => {
    const result = parseArtifact({ retention: "  value  " });
    expect(result.retention).toBe("value");
  });

  test("retention rejects empty text", () => {
    const input = { retention: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("retention rejects nontext input", () => {
    const input = { retention: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("retention accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ retention: text }).retention).toBe(text);
  });

  test("retention rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ retention: text })).toThrow();
  });

  test("retention leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "retention")).toBe(false);
  });

  test("sourceKey accepts a normalized value", () => {
    const result = parseArtifact({ sourceKey: "value" });
    expect(result.sourceKey).toBe("value");
  });

  test("sourceKey trims surrounding whitespace", () => {
    const result = parseArtifact({ sourceKey: "  value  " });
    expect(result.sourceKey).toBe("value");
  });

  test("sourceKey rejects empty text", () => {
    const input = { sourceKey: "   " };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("sourceKey rejects nontext input", () => {
    const input = { sourceKey: 42 };
    expect(() => parseArtifact(input)).toThrow();
  });

  test("sourceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseArtifact({ sourceKey: text }).sourceKey).toBe(text);
  });

  test("sourceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseArtifact({ sourceKey: text })).toThrow();
  });

  test("sourceKey leaves omitted values absent", () => {
    const result = parseArtifact({});
    expect(Object.hasOwn(result, "sourceKey")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseArtifact({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseArtifact(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseArtifact({ title: "before", description: "keep" });
    const changed = patchArtifact(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeArtifact(left)).toBe(serializeArtifact(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalArtifact({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalArtifact({ title: "a" }, { title: "b" })).toBe(false);
  });
});

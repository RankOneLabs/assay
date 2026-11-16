import { describe, expect, test } from "bun:test";
import { parseAttachment, patchAttachment, serializeAttachment, equalAttachment } from "../../src/payloads/attachment.ts";

describe("attachment payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseAttachment({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseAttachment({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseAttachment({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseAttachment({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("caseKey accepts a normalized value", () => {
    const result = parseAttachment({ caseKey: "value" });
    expect(result.caseKey).toBe("value");
  });

  test("caseKey trims surrounding whitespace", () => {
    const result = parseAttachment({ caseKey: "  value  " });
    expect(result.caseKey).toBe("value");
  });

  test("caseKey rejects empty text", () => {
    const input = { caseKey: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("caseKey rejects nontext input", () => {
    const input = { caseKey: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("caseKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ caseKey: text }).caseKey).toBe(text);
  });

  test("caseKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ caseKey: text })).toThrow();
  });

  test("caseKey leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "caseKey")).toBe(false);
  });

  test("artifactKey accepts a normalized value", () => {
    const result = parseAttachment({ artifactKey: "value" });
    expect(result.artifactKey).toBe("value");
  });

  test("artifactKey trims surrounding whitespace", () => {
    const result = parseAttachment({ artifactKey: "  value  " });
    expect(result.artifactKey).toBe("value");
  });

  test("artifactKey rejects empty text", () => {
    const input = { artifactKey: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("artifactKey rejects nontext input", () => {
    const input = { artifactKey: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("artifactKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ artifactKey: text }).artifactKey).toBe(text);
  });

  test("artifactKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ artifactKey: text })).toThrow();
  });

  test("artifactKey leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "artifactKey")).toBe(false);
  });

  test("filename accepts a normalized value", () => {
    const result = parseAttachment({ filename: "value" });
    expect(result.filename).toBe("value");
  });

  test("filename trims surrounding whitespace", () => {
    const result = parseAttachment({ filename: "  value  " });
    expect(result.filename).toBe("value");
  });

  test("filename rejects empty text", () => {
    const input = { filename: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("filename rejects nontext input", () => {
    const input = { filename: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("filename accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ filename: text }).filename).toBe(text);
  });

  test("filename rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ filename: text })).toThrow();
  });

  test("filename leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "filename")).toBe(false);
  });

  test("mediaType accepts a normalized value", () => {
    const result = parseAttachment({ mediaType: "value" });
    expect(result.mediaType).toBe("value");
  });

  test("mediaType trims surrounding whitespace", () => {
    const result = parseAttachment({ mediaType: "  value  " });
    expect(result.mediaType).toBe("value");
  });

  test("mediaType rejects empty text", () => {
    const input = { mediaType: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("mediaType rejects nontext input", () => {
    const input = { mediaType: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("mediaType accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ mediaType: text }).mediaType).toBe(text);
  });

  test("mediaType rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ mediaType: text })).toThrow();
  });

  test("mediaType leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "mediaType")).toBe(false);
  });

  test("checksum accepts a normalized value", () => {
    const result = parseAttachment({ checksum: "value" });
    expect(result.checksum).toBe("value");
  });

  test("checksum trims surrounding whitespace", () => {
    const result = parseAttachment({ checksum: "  value  " });
    expect(result.checksum).toBe("value");
  });

  test("checksum rejects empty text", () => {
    const input = { checksum: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("checksum rejects nontext input", () => {
    const input = { checksum: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("checksum accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ checksum: text }).checksum).toBe(text);
  });

  test("checksum rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ checksum: text })).toThrow();
  });

  test("checksum leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "checksum")).toBe(false);
  });

  test("sourceKey accepts a normalized value", () => {
    const result = parseAttachment({ sourceKey: "value" });
    expect(result.sourceKey).toBe("value");
  });

  test("sourceKey trims surrounding whitespace", () => {
    const result = parseAttachment({ sourceKey: "  value  " });
    expect(result.sourceKey).toBe("value");
  });

  test("sourceKey rejects empty text", () => {
    const input = { sourceKey: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("sourceKey rejects nontext input", () => {
    const input = { sourceKey: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("sourceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ sourceKey: text }).sourceKey).toBe(text);
  });

  test("sourceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ sourceKey: text })).toThrow();
  });

  test("sourceKey leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "sourceKey")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseAttachment({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseAttachment({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("caption accepts a normalized value", () => {
    const result = parseAttachment({ caption: "value" });
    expect(result.caption).toBe("value");
  });

  test("caption trims surrounding whitespace", () => {
    const result = parseAttachment({ caption: "  value  " });
    expect(result.caption).toBe("value");
  });

  test("caption rejects empty text", () => {
    const input = { caption: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("caption rejects nontext input", () => {
    const input = { caption: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("caption accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ caption: text }).caption).toBe(text);
  });

  test("caption rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ caption: text })).toThrow();
  });

  test("caption leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "caption")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseAttachment({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseAttachment({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("retention accepts a normalized value", () => {
    const result = parseAttachment({ retention: "value" });
    expect(result.retention).toBe("value");
  });

  test("retention trims surrounding whitespace", () => {
    const result = parseAttachment({ retention: "  value  " });
    expect(result.retention).toBe("value");
  });

  test("retention rejects empty text", () => {
    const input = { retention: "   " };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("retention rejects nontext input", () => {
    const input = { retention: 42 };
    expect(() => parseAttachment(input)).toThrow();
  });

  test("retention accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseAttachment({ retention: text }).retention).toBe(text);
  });

  test("retention rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseAttachment({ retention: text })).toThrow();
  });

  test("retention leaves omitted values absent", () => {
    const result = parseAttachment({});
    expect(Object.hasOwn(result, "retention")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseAttachment({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseAttachment(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseAttachment({ title: "before", description: "keep" });
    const changed = patchAttachment(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeAttachment(left)).toBe(serializeAttachment(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalAttachment({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalAttachment({ title: "a" }, { title: "b" })).toBe(false);
  });
});

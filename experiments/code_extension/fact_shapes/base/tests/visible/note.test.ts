import { describe, expect, test } from "bun:test";
import { parseNote, patchNote, serializeNote, equalNote } from "../../src/payloads/note.ts";

describe("note payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseNote({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseNote({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseNote({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseNote({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("caseKey accepts a normalized value", () => {
    const result = parseNote({ caseKey: "value" });
    expect(result.caseKey).toBe("value");
  });

  test("caseKey trims surrounding whitespace", () => {
    const result = parseNote({ caseKey: "  value  " });
    expect(result.caseKey).toBe("value");
  });

  test("caseKey rejects empty text", () => {
    const input = { caseKey: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("caseKey rejects nontext input", () => {
    const input = { caseKey: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("caseKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ caseKey: text }).caseKey).toBe(text);
  });

  test("caseKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ caseKey: text })).toThrow();
  });

  test("caseKey leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "caseKey")).toBe(false);
  });

  test("authorKey accepts a normalized value", () => {
    const result = parseNote({ authorKey: "value" });
    expect(result.authorKey).toBe("value");
  });

  test("authorKey trims surrounding whitespace", () => {
    const result = parseNote({ authorKey: "  value  " });
    expect(result.authorKey).toBe("value");
  });

  test("authorKey rejects empty text", () => {
    const input = { authorKey: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("authorKey rejects nontext input", () => {
    const input = { authorKey: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("authorKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ authorKey: text }).authorKey).toBe(text);
  });

  test("authorKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ authorKey: text })).toThrow();
  });

  test("authorKey leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "authorKey")).toBe(false);
  });

  test("body accepts a normalized value", () => {
    const result = parseNote({ body: "value" });
    expect(result.body).toBe("value");
  });

  test("body trims surrounding whitespace", () => {
    const result = parseNote({ body: "  value  " });
    expect(result.body).toBe("value");
  });

  test("body rejects empty text", () => {
    const input = { body: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("body rejects nontext input", () => {
    const input = { body: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("body accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ body: text }).body).toBe(text);
  });

  test("body rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ body: text })).toThrow();
  });

  test("body leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "body")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseNote({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseNote({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("category accepts a normalized value", () => {
    const result = parseNote({ category: "value" });
    expect(result.category).toBe("value");
  });

  test("category trims surrounding whitespace", () => {
    const result = parseNote({ category: "  value  " });
    expect(result.category).toBe("value");
  });

  test("category rejects empty text", () => {
    const input = { category: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("category rejects nontext input", () => {
    const input = { category: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("category accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ category: text }).category).toBe(text);
  });

  test("category rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ category: text })).toThrow();
  });

  test("category leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "category")).toBe(false);
  });

  test("sourceKey accepts a normalized value", () => {
    const result = parseNote({ sourceKey: "value" });
    expect(result.sourceKey).toBe("value");
  });

  test("sourceKey trims surrounding whitespace", () => {
    const result = parseNote({ sourceKey: "  value  " });
    expect(result.sourceKey).toBe("value");
  });

  test("sourceKey rejects empty text", () => {
    const input = { sourceKey: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("sourceKey rejects nontext input", () => {
    const input = { sourceKey: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("sourceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ sourceKey: text }).sourceKey).toBe(text);
  });

  test("sourceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ sourceKey: text })).toThrow();
  });

  test("sourceKey leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "sourceKey")).toBe(false);
  });

  test("threadKey accepts a normalized value", () => {
    const result = parseNote({ threadKey: "value" });
    expect(result.threadKey).toBe("value");
  });

  test("threadKey trims surrounding whitespace", () => {
    const result = parseNote({ threadKey: "  value  " });
    expect(result.threadKey).toBe("value");
  });

  test("threadKey rejects empty text", () => {
    const input = { threadKey: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("threadKey rejects nontext input", () => {
    const input = { threadKey: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("threadKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ threadKey: text }).threadKey).toBe(text);
  });

  test("threadKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ threadKey: text })).toThrow();
  });

  test("threadKey leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "threadKey")).toBe(false);
  });

  test("parentKey accepts a normalized value", () => {
    const result = parseNote({ parentKey: "value" });
    expect(result.parentKey).toBe("value");
  });

  test("parentKey trims surrounding whitespace", () => {
    const result = parseNote({ parentKey: "  value  " });
    expect(result.parentKey).toBe("value");
  });

  test("parentKey rejects empty text", () => {
    const input = { parentKey: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("parentKey rejects nontext input", () => {
    const input = { parentKey: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("parentKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ parentKey: text }).parentKey).toBe(text);
  });

  test("parentKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ parentKey: text })).toThrow();
  });

  test("parentKey leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "parentKey")).toBe(false);
  });

  test("correlationKey accepts a normalized value", () => {
    const result = parseNote({ correlationKey: "value" });
    expect(result.correlationKey).toBe("value");
  });

  test("correlationKey trims surrounding whitespace", () => {
    const result = parseNote({ correlationKey: "  value  " });
    expect(result.correlationKey).toBe("value");
  });

  test("correlationKey rejects empty text", () => {
    const input = { correlationKey: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("correlationKey rejects nontext input", () => {
    const input = { correlationKey: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("correlationKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ correlationKey: text }).correlationKey).toBe(text);
  });

  test("correlationKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ correlationKey: text })).toThrow();
  });

  test("correlationKey leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "correlationKey")).toBe(false);
  });

  test("visibility accepts a normalized value", () => {
    const result = parseNote({ visibility: "value" });
    expect(result.visibility).toBe("value");
  });

  test("visibility trims surrounding whitespace", () => {
    const result = parseNote({ visibility: "  value  " });
    expect(result.visibility).toBe("value");
  });

  test("visibility rejects empty text", () => {
    const input = { visibility: "   " };
    expect(() => parseNote(input)).toThrow();
  });

  test("visibility rejects nontext input", () => {
    const input = { visibility: 42 };
    expect(() => parseNote(input)).toThrow();
  });

  test("visibility accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseNote({ visibility: text }).visibility).toBe(text);
  });

  test("visibility rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseNote({ visibility: text })).toThrow();
  });

  test("visibility leaves omitted values absent", () => {
    const result = parseNote({});
    expect(Object.hasOwn(result, "visibility")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseNote({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseNote(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseNote({ title: "before", description: "keep" });
    const changed = patchNote(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeNote(left)).toBe(serializeNote(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalNote({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalNote({ title: "a" }, { title: "b" })).toBe(false);
  });
});

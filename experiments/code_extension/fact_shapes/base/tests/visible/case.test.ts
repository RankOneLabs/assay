import { describe, expect, test } from "bun:test";
import { parseCase, patchCase, serializeCase, equalCase } from "../../src/payloads/case.ts";

describe("case payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseCase({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseCase({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseCase({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseCase({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseCase({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseCase({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("projectKey accepts a normalized value", () => {
    const result = parseCase({ projectKey: "value" });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey trims surrounding whitespace", () => {
    const result = parseCase({ projectKey: "  value  " });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey rejects empty text", () => {
    const input = { projectKey: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("projectKey rejects nontext input", () => {
    const input = { projectKey: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("projectKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ projectKey: text }).projectKey).toBe(text);
  });

  test("projectKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ projectKey: text })).toThrow();
  });

  test("projectKey leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "projectKey")).toBe(false);
  });

  test("externalKey accepts a normalized value", () => {
    const result = parseCase({ externalKey: "value" });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey trims surrounding whitespace", () => {
    const result = parseCase({ externalKey: "  value  " });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey rejects empty text", () => {
    const input = { externalKey: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("externalKey rejects nontext input", () => {
    const input = { externalKey: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("externalKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ externalKey: text }).externalKey).toBe(text);
  });

  test("externalKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ externalKey: text })).toThrow();
  });

  test("externalKey leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "externalKey")).toBe(false);
  });

  test("category accepts a normalized value", () => {
    const result = parseCase({ category: "value" });
    expect(result.category).toBe("value");
  });

  test("category trims surrounding whitespace", () => {
    const result = parseCase({ category: "  value  " });
    expect(result.category).toBe("value");
  });

  test("category rejects empty text", () => {
    const input = { category: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("category rejects nontext input", () => {
    const input = { category: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("category accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ category: text }).category).toBe(text);
  });

  test("category rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ category: text })).toThrow();
  });

  test("category leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "category")).toBe(false);
  });

  test("subject accepts a normalized value", () => {
    const result = parseCase({ subject: "value" });
    expect(result.subject).toBe("value");
  });

  test("subject trims surrounding whitespace", () => {
    const result = parseCase({ subject: "  value  " });
    expect(result.subject).toBe("value");
  });

  test("subject rejects empty text", () => {
    const input = { subject: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("subject rejects nontext input", () => {
    const input = { subject: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("subject accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ subject: text }).subject).toBe(text);
  });

  test("subject rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ subject: text })).toThrow();
  });

  test("subject leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "subject")).toBe(false);
  });

  test("reporter accepts a normalized value", () => {
    const result = parseCase({ reporter: "value" });
    expect(result.reporter).toBe("value");
  });

  test("reporter trims surrounding whitespace", () => {
    const result = parseCase({ reporter: "  value  " });
    expect(result.reporter).toBe("value");
  });

  test("reporter rejects empty text", () => {
    const input = { reporter: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("reporter rejects nontext input", () => {
    const input = { reporter: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("reporter accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ reporter: text }).reporter).toBe(text);
  });

  test("reporter rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ reporter: text })).toThrow();
  });

  test("reporter leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "reporter")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseCase({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseCase({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseCase({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseCase({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("summary accepts a normalized value", () => {
    const result = parseCase({ summary: "value" });
    expect(result.summary).toBe("value");
  });

  test("summary trims surrounding whitespace", () => {
    const result = parseCase({ summary: "  value  " });
    expect(result.summary).toBe("value");
  });

  test("summary rejects empty text", () => {
    const input = { summary: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("summary rejects nontext input", () => {
    const input = { summary: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("summary accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ summary: text }).summary).toBe(text);
  });

  test("summary rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ summary: text })).toThrow();
  });

  test("summary leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "summary")).toBe(false);
  });

  test("resolution accepts a normalized value", () => {
    const result = parseCase({ resolution: "value" });
    expect(result.resolution).toBe("value");
  });

  test("resolution trims surrounding whitespace", () => {
    const result = parseCase({ resolution: "  value  " });
    expect(result.resolution).toBe("value");
  });

  test("resolution rejects empty text", () => {
    const input = { resolution: "   " };
    expect(() => parseCase(input)).toThrow();
  });

  test("resolution rejects nontext input", () => {
    const input = { resolution: 42 };
    expect(() => parseCase(input)).toThrow();
  });

  test("resolution accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseCase({ resolution: text }).resolution).toBe(text);
  });

  test("resolution rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseCase({ resolution: text })).toThrow();
  });

  test("resolution leaves omitted values absent", () => {
    const result = parseCase({});
    expect(Object.hasOwn(result, "resolution")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseCase({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseCase(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseCase({ title: "before", description: "keep" });
    const changed = patchCase(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeCase(left)).toBe(serializeCase(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalCase({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalCase({ title: "a" }, { title: "b" })).toBe(false);
  });
});

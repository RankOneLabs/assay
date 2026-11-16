import { describe, expect, test } from "bun:test";
import { parseLabel, patchLabel, serializeLabel, equalLabel } from "../../src/payloads/label.ts";

describe("label payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseLabel({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseLabel({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseLabel({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseLabel({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("projectKey accepts a normalized value", () => {
    const result = parseLabel({ projectKey: "value" });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey trims surrounding whitespace", () => {
    const result = parseLabel({ projectKey: "  value  " });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey rejects empty text", () => {
    const input = { projectKey: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("projectKey rejects nontext input", () => {
    const input = { projectKey: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("projectKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ projectKey: text }).projectKey).toBe(text);
  });

  test("projectKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ projectKey: text })).toThrow();
  });

  test("projectKey leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "projectKey")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseLabel({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseLabel({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("color accepts a normalized value", () => {
    const result = parseLabel({ color: "value" });
    expect(result.color).toBe("value");
  });

  test("color trims surrounding whitespace", () => {
    const result = parseLabel({ color: "  value  " });
    expect(result.color).toBe("value");
  });

  test("color rejects empty text", () => {
    const input = { color: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("color rejects nontext input", () => {
    const input = { color: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("color accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ color: text }).color).toBe(text);
  });

  test("color rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ color: text })).toThrow();
  });

  test("color leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "color")).toBe(false);
  });

  test("category accepts a normalized value", () => {
    const result = parseLabel({ category: "value" });
    expect(result.category).toBe("value");
  });

  test("category trims surrounding whitespace", () => {
    const result = parseLabel({ category: "  value  " });
    expect(result.category).toBe("value");
  });

  test("category rejects empty text", () => {
    const input = { category: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("category rejects nontext input", () => {
    const input = { category: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("category accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ category: text }).category).toBe(text);
  });

  test("category rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ category: text })).toThrow();
  });

  test("category leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "category")).toBe(false);
  });

  test("namespace accepts a normalized value", () => {
    const result = parseLabel({ namespace: "value" });
    expect(result.namespace).toBe("value");
  });

  test("namespace trims surrounding whitespace", () => {
    const result = parseLabel({ namespace: "  value  " });
    expect(result.namespace).toBe("value");
  });

  test("namespace rejects empty text", () => {
    const input = { namespace: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("namespace rejects nontext input", () => {
    const input = { namespace: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("namespace accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ namespace: text }).namespace).toBe(text);
  });

  test("namespace rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ namespace: text })).toThrow();
  });

  test("namespace leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "namespace")).toBe(false);
  });

  test("externalKey accepts a normalized value", () => {
    const result = parseLabel({ externalKey: "value" });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey trims surrounding whitespace", () => {
    const result = parseLabel({ externalKey: "  value  " });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey rejects empty text", () => {
    const input = { externalKey: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("externalKey rejects nontext input", () => {
    const input = { externalKey: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("externalKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ externalKey: text }).externalKey).toBe(text);
  });

  test("externalKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ externalKey: text })).toThrow();
  });

  test("externalKey leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "externalKey")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseLabel({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseLabel({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("displayName accepts a normalized value", () => {
    const result = parseLabel({ displayName: "value" });
    expect(result.displayName).toBe("value");
  });

  test("displayName trims surrounding whitespace", () => {
    const result = parseLabel({ displayName: "  value  " });
    expect(result.displayName).toBe("value");
  });

  test("displayName rejects empty text", () => {
    const input = { displayName: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("displayName rejects nontext input", () => {
    const input = { displayName: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("displayName accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ displayName: text }).displayName).toBe(text);
  });

  test("displayName rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ displayName: text })).toThrow();
  });

  test("displayName leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "displayName")).toBe(false);
  });

  test("shortName accepts a normalized value", () => {
    const result = parseLabel({ shortName: "value" });
    expect(result.shortName).toBe("value");
  });

  test("shortName trims surrounding whitespace", () => {
    const result = parseLabel({ shortName: "  value  " });
    expect(result.shortName).toBe("value");
  });

  test("shortName rejects empty text", () => {
    const input = { shortName: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("shortName rejects nontext input", () => {
    const input = { shortName: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("shortName accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ shortName: text }).shortName).toBe(text);
  });

  test("shortName rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ shortName: text })).toThrow();
  });

  test("shortName leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "shortName")).toBe(false);
  });

  test("helpText accepts a normalized value", () => {
    const result = parseLabel({ helpText: "value" });
    expect(result.helpText).toBe("value");
  });

  test("helpText trims surrounding whitespace", () => {
    const result = parseLabel({ helpText: "  value  " });
    expect(result.helpText).toBe("value");
  });

  test("helpText rejects empty text", () => {
    const input = { helpText: "   " };
    expect(() => parseLabel(input)).toThrow();
  });

  test("helpText rejects nontext input", () => {
    const input = { helpText: 42 };
    expect(() => parseLabel(input)).toThrow();
  });

  test("helpText accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseLabel({ helpText: text }).helpText).toBe(text);
  });

  test("helpText rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseLabel({ helpText: text })).toThrow();
  });

  test("helpText leaves omitted values absent", () => {
    const result = parseLabel({});
    expect(Object.hasOwn(result, "helpText")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseLabel({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseLabel(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseLabel({ title: "before", description: "keep" });
    const changed = patchLabel(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeLabel(left)).toBe(serializeLabel(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalLabel({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalLabel({ title: "a" }, { title: "b" })).toBe(false);
  });
});

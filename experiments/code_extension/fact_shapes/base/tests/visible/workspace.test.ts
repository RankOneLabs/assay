import { describe, expect, test } from "bun:test";
import { parseWorkspace, patchWorkspace, serializeWorkspace, equalWorkspace } from "../../src/payloads/workspace.ts";

describe("workspace payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseWorkspace({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseWorkspace({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseWorkspace({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseWorkspace({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseWorkspace({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseWorkspace({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseWorkspace({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseWorkspace({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseWorkspace({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseWorkspace({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("organizationKey accepts a normalized value", () => {
    const result = parseWorkspace({ organizationKey: "value" });
    expect(result.organizationKey).toBe("value");
  });

  test("organizationKey trims surrounding whitespace", () => {
    const result = parseWorkspace({ organizationKey: "  value  " });
    expect(result.organizationKey).toBe("value");
  });

  test("organizationKey rejects empty text", () => {
    const input = { organizationKey: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("organizationKey rejects nontext input", () => {
    const input = { organizationKey: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("organizationKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ organizationKey: text }).organizationKey).toBe(text);
  });

  test("organizationKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ organizationKey: text })).toThrow();
  });

  test("organizationKey leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "organizationKey")).toBe(false);
  });

  test("contact accepts a normalized value", () => {
    const result = parseWorkspace({ contact: "value" });
    expect(result.contact).toBe("value");
  });

  test("contact trims surrounding whitespace", () => {
    const result = parseWorkspace({ contact: "  value  " });
    expect(result.contact).toBe("value");
  });

  test("contact rejects empty text", () => {
    const input = { contact: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("contact rejects nontext input", () => {
    const input = { contact: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("contact accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ contact: text }).contact).toBe(text);
  });

  test("contact rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ contact: text })).toThrow();
  });

  test("contact leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "contact")).toBe(false);
  });

  test("domain accepts a normalized value", () => {
    const result = parseWorkspace({ domain: "value" });
    expect(result.domain).toBe("value");
  });

  test("domain trims surrounding whitespace", () => {
    const result = parseWorkspace({ domain: "  value  " });
    expect(result.domain).toBe("value");
  });

  test("domain rejects empty text", () => {
    const input = { domain: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("domain rejects nontext input", () => {
    const input = { domain: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("domain accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ domain: text }).domain).toBe(text);
  });

  test("domain rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ domain: text })).toThrow();
  });

  test("domain leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "domain")).toBe(false);
  });

  test("externalKey accepts a normalized value", () => {
    const result = parseWorkspace({ externalKey: "value" });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey trims surrounding whitespace", () => {
    const result = parseWorkspace({ externalKey: "  value  " });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey rejects empty text", () => {
    const input = { externalKey: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("externalKey rejects nontext input", () => {
    const input = { externalKey: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("externalKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ externalKey: text }).externalKey).toBe(text);
  });

  test("externalKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ externalKey: text })).toThrow();
  });

  test("externalKey leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "externalKey")).toBe(false);
  });

  test("costCenter accepts a normalized value", () => {
    const result = parseWorkspace({ costCenter: "value" });
    expect(result.costCenter).toBe("value");
  });

  test("costCenter trims surrounding whitespace", () => {
    const result = parseWorkspace({ costCenter: "  value  " });
    expect(result.costCenter).toBe("value");
  });

  test("costCenter rejects empty text", () => {
    const input = { costCenter: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("costCenter rejects nontext input", () => {
    const input = { costCenter: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("costCenter accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ costCenter: text }).costCenter).toBe(text);
  });

  test("costCenter rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ costCenter: text })).toThrow();
  });

  test("costCenter leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "costCenter")).toBe(false);
  });

  test("retention accepts a normalized value", () => {
    const result = parseWorkspace({ retention: "value" });
    expect(result.retention).toBe("value");
  });

  test("retention trims surrounding whitespace", () => {
    const result = parseWorkspace({ retention: "  value  " });
    expect(result.retention).toBe("value");
  });

  test("retention rejects empty text", () => {
    const input = { retention: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("retention rejects nontext input", () => {
    const input = { retention: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("retention accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ retention: text }).retention).toBe(text);
  });

  test("retention rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ retention: text })).toThrow();
  });

  test("retention leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "retention")).toBe(false);
  });

  test("timezone accepts a normalized value", () => {
    const result = parseWorkspace({ timezone: "value" });
    expect(result.timezone).toBe("value");
  });

  test("timezone trims surrounding whitespace", () => {
    const result = parseWorkspace({ timezone: "  value  " });
    expect(result.timezone).toBe("value");
  });

  test("timezone rejects empty text", () => {
    const input = { timezone: "   " };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("timezone rejects nontext input", () => {
    const input = { timezone: 42 };
    expect(() => parseWorkspace(input)).toThrow();
  });

  test("timezone accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorkspace({ timezone: text }).timezone).toBe(text);
  });

  test("timezone rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorkspace({ timezone: text })).toThrow();
  });

  test("timezone leaves omitted values absent", () => {
    const result = parseWorkspace({});
    expect(Object.hasOwn(result, "timezone")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseWorkspace({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseWorkspace(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseWorkspace({ title: "before", description: "keep" });
    const changed = patchWorkspace(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeWorkspace(left)).toBe(serializeWorkspace(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalWorkspace({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalWorkspace({ title: "a" }, { title: "b" })).toBe(false);
  });
});

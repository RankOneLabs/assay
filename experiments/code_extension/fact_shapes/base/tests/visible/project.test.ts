import { describe, expect, test } from "bun:test";
import { parseProject, patchProject, serializeProject, equalProject } from "../../src/payloads/project.ts";

describe("project payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseProject({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseProject({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseProject({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseProject({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("workspaceKey accepts a normalized value", () => {
    const result = parseProject({ workspaceKey: "value" });
    expect(result.workspaceKey).toBe("value");
  });

  test("workspaceKey trims surrounding whitespace", () => {
    const result = parseProject({ workspaceKey: "  value  " });
    expect(result.workspaceKey).toBe("value");
  });

  test("workspaceKey rejects empty text", () => {
    const input = { workspaceKey: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("workspaceKey rejects nontext input", () => {
    const input = { workspaceKey: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("workspaceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ workspaceKey: text }).workspaceKey).toBe(text);
  });

  test("workspaceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ workspaceKey: text })).toThrow();
  });

  test("workspaceKey leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "workspaceKey")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseProject({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseProject({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseProject({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseProject({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("locale accepts a normalized value", () => {
    const result = parseProject({ locale: "value" });
    expect(result.locale).toBe("value");
  });

  test("locale trims surrounding whitespace", () => {
    const result = parseProject({ locale: "  value  " });
    expect(result.locale).toBe("value");
  });

  test("locale rejects empty text", () => {
    const input = { locale: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("locale rejects nontext input", () => {
    const input = { locale: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("locale accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ locale: text }).locale).toBe(text);
  });

  test("locale rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ locale: text })).toThrow();
  });

  test("locale leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "locale")).toBe(false);
  });

  test("repositoryKey accepts a normalized value", () => {
    const result = parseProject({ repositoryKey: "value" });
    expect(result.repositoryKey).toBe("value");
  });

  test("repositoryKey trims surrounding whitespace", () => {
    const result = parseProject({ repositoryKey: "  value  " });
    expect(result.repositoryKey).toBe("value");
  });

  test("repositoryKey rejects empty text", () => {
    const input = { repositoryKey: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("repositoryKey rejects nontext input", () => {
    const input = { repositoryKey: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("repositoryKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ repositoryKey: text }).repositoryKey).toBe(text);
  });

  test("repositoryKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ repositoryKey: text })).toThrow();
  });

  test("repositoryKey leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "repositoryKey")).toBe(false);
  });

  test("contact accepts a normalized value", () => {
    const result = parseProject({ contact: "value" });
    expect(result.contact).toBe("value");
  });

  test("contact trims surrounding whitespace", () => {
    const result = parseProject({ contact: "  value  " });
    expect(result.contact).toBe("value");
  });

  test("contact rejects empty text", () => {
    const input = { contact: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("contact rejects nontext input", () => {
    const input = { contact: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("contact accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ contact: text }).contact).toBe(text);
  });

  test("contact rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ contact: text })).toThrow();
  });

  test("contact leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "contact")).toBe(false);
  });

  test("externalKey accepts a normalized value", () => {
    const result = parseProject({ externalKey: "value" });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey trims surrounding whitespace", () => {
    const result = parseProject({ externalKey: "  value  " });
    expect(result.externalKey).toBe("value");
  });

  test("externalKey rejects empty text", () => {
    const input = { externalKey: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("externalKey rejects nontext input", () => {
    const input = { externalKey: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("externalKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ externalKey: text }).externalKey).toBe(text);
  });

  test("externalKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ externalKey: text })).toThrow();
  });

  test("externalKey leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "externalKey")).toBe(false);
  });

  test("category accepts a normalized value", () => {
    const result = parseProject({ category: "value" });
    expect(result.category).toBe("value");
  });

  test("category trims surrounding whitespace", () => {
    const result = parseProject({ category: "  value  " });
    expect(result.category).toBe("value");
  });

  test("category rejects empty text", () => {
    const input = { category: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("category rejects nontext input", () => {
    const input = { category: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("category accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ category: text }).category).toBe(text);
  });

  test("category rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ category: text })).toThrow();
  });

  test("category leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "category")).toBe(false);
  });

  test("costCenter accepts a normalized value", () => {
    const result = parseProject({ costCenter: "value" });
    expect(result.costCenter).toBe("value");
  });

  test("costCenter trims surrounding whitespace", () => {
    const result = parseProject({ costCenter: "  value  " });
    expect(result.costCenter).toBe("value");
  });

  test("costCenter rejects empty text", () => {
    const input = { costCenter: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("costCenter rejects nontext input", () => {
    const input = { costCenter: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("costCenter accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ costCenter: text }).costCenter).toBe(text);
  });

  test("costCenter rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ costCenter: text })).toThrow();
  });

  test("costCenter leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "costCenter")).toBe(false);
  });

  test("retention accepts a normalized value", () => {
    const result = parseProject({ retention: "value" });
    expect(result.retention).toBe("value");
  });

  test("retention trims surrounding whitespace", () => {
    const result = parseProject({ retention: "  value  " });
    expect(result.retention).toBe("value");
  });

  test("retention rejects empty text", () => {
    const input = { retention: "   " };
    expect(() => parseProject(input)).toThrow();
  });

  test("retention rejects nontext input", () => {
    const input = { retention: 42 };
    expect(() => parseProject(input)).toThrow();
  });

  test("retention accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseProject({ retention: text }).retention).toBe(text);
  });

  test("retention rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseProject({ retention: text })).toThrow();
  });

  test("retention leaves omitted values absent", () => {
    const result = parseProject({});
    expect(Object.hasOwn(result, "retention")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseProject({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseProject(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseProject({ title: "before", description: "keep" });
    const changed = patchProject(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeProject(left)).toBe(serializeProject(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalProject({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalProject({ title: "a" }, { title: "b" })).toBe(false);
  });
});

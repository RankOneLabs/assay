import { describe, expect, test } from "bun:test";
import { parseWorker, patchWorker, serializeWorker, equalWorker } from "../../src/payloads/worker.ts";

describe("worker payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseWorker({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseWorker({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseWorker({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseWorker({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("poolKey accepts a normalized value", () => {
    const result = parseWorker({ poolKey: "value" });
    expect(result.poolKey).toBe("value");
  });

  test("poolKey trims surrounding whitespace", () => {
    const result = parseWorker({ poolKey: "  value  " });
    expect(result.poolKey).toBe("value");
  });

  test("poolKey rejects empty text", () => {
    const input = { poolKey: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("poolKey rejects nontext input", () => {
    const input = { poolKey: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("poolKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ poolKey: text }).poolKey).toBe(text);
  });

  test("poolKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ poolKey: text })).toThrow();
  });

  test("poolKey leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "poolKey")).toBe(false);
  });

  test("hostKey accepts a normalized value", () => {
    const result = parseWorker({ hostKey: "value" });
    expect(result.hostKey).toBe("value");
  });

  test("hostKey trims surrounding whitespace", () => {
    const result = parseWorker({ hostKey: "  value  " });
    expect(result.hostKey).toBe("value");
  });

  test("hostKey rejects empty text", () => {
    const input = { hostKey: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("hostKey rejects nontext input", () => {
    const input = { hostKey: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("hostKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ hostKey: text }).hostKey).toBe(text);
  });

  test("hostKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ hostKey: text })).toThrow();
  });

  test("hostKey leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "hostKey")).toBe(false);
  });

  test("runtime accepts a normalized value", () => {
    const result = parseWorker({ runtime: "value" });
    expect(result.runtime).toBe("value");
  });

  test("runtime trims surrounding whitespace", () => {
    const result = parseWorker({ runtime: "  value  " });
    expect(result.runtime).toBe("value");
  });

  test("runtime rejects empty text", () => {
    const input = { runtime: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("runtime rejects nontext input", () => {
    const input = { runtime: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("runtime accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ runtime: text }).runtime).toBe(text);
  });

  test("runtime rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ runtime: text })).toThrow();
  });

  test("runtime leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "runtime")).toBe(false);
  });

  test("version accepts a normalized value", () => {
    const result = parseWorker({ version: "value" });
    expect(result.version).toBe("value");
  });

  test("version trims surrounding whitespace", () => {
    const result = parseWorker({ version: "  value  " });
    expect(result.version).toBe("value");
  });

  test("version rejects empty text", () => {
    const input = { version: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("version rejects nontext input", () => {
    const input = { version: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("version accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ version: text }).version).toBe(text);
  });

  test("version rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ version: text })).toThrow();
  });

  test("version leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "version")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseWorker({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseWorker({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("architecture accepts a normalized value", () => {
    const result = parseWorker({ architecture: "value" });
    expect(result.architecture).toBe("value");
  });

  test("architecture trims surrounding whitespace", () => {
    const result = parseWorker({ architecture: "  value  " });
    expect(result.architecture).toBe("value");
  });

  test("architecture rejects empty text", () => {
    const input = { architecture: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("architecture rejects nontext input", () => {
    const input = { architecture: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("architecture accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ architecture: text }).architecture).toBe(text);
  });

  test("architecture rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ architecture: text })).toThrow();
  });

  test("architecture leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "architecture")).toBe(false);
  });

  test("capability accepts a normalized value", () => {
    const result = parseWorker({ capability: "value" });
    expect(result.capability).toBe("value");
  });

  test("capability trims surrounding whitespace", () => {
    const result = parseWorker({ capability: "  value  " });
    expect(result.capability).toBe("value");
  });

  test("capability rejects empty text", () => {
    const input = { capability: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("capability rejects nontext input", () => {
    const input = { capability: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("capability accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ capability: text }).capability).toBe(text);
  });

  test("capability rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ capability: text })).toThrow();
  });

  test("capability leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "capability")).toBe(false);
  });

  test("contact accepts a normalized value", () => {
    const result = parseWorker({ contact: "value" });
    expect(result.contact).toBe("value");
  });

  test("contact trims surrounding whitespace", () => {
    const result = parseWorker({ contact: "  value  " });
    expect(result.contact).toBe("value");
  });

  test("contact rejects empty text", () => {
    const input = { contact: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("contact rejects nontext input", () => {
    const input = { contact: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("contact accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ contact: text }).contact).toBe(text);
  });

  test("contact rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ contact: text })).toThrow();
  });

  test("contact leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "contact")).toBe(false);
  });

  test("certificate accepts a normalized value", () => {
    const result = parseWorker({ certificate: "value" });
    expect(result.certificate).toBe("value");
  });

  test("certificate trims surrounding whitespace", () => {
    const result = parseWorker({ certificate: "  value  " });
    expect(result.certificate).toBe("value");
  });

  test("certificate rejects empty text", () => {
    const input = { certificate: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("certificate rejects nontext input", () => {
    const input = { certificate: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("certificate accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ certificate: text }).certificate).toBe(text);
  });

  test("certificate rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ certificate: text })).toThrow();
  });

  test("certificate leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "certificate")).toBe(false);
  });

  test("imageKey accepts a normalized value", () => {
    const result = parseWorker({ imageKey: "value" });
    expect(result.imageKey).toBe("value");
  });

  test("imageKey trims surrounding whitespace", () => {
    const result = parseWorker({ imageKey: "  value  " });
    expect(result.imageKey).toBe("value");
  });

  test("imageKey rejects empty text", () => {
    const input = { imageKey: "   " };
    expect(() => parseWorker(input)).toThrow();
  });

  test("imageKey rejects nontext input", () => {
    const input = { imageKey: 42 };
    expect(() => parseWorker(input)).toThrow();
  });

  test("imageKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseWorker({ imageKey: text }).imageKey).toBe(text);
  });

  test("imageKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseWorker({ imageKey: text })).toThrow();
  });

  test("imageKey leaves omitted values absent", () => {
    const result = parseWorker({});
    expect(Object.hasOwn(result, "imageKey")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseWorker({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseWorker(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseWorker({ title: "before", description: "keep" });
    const changed = patchWorker(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeWorker(left)).toBe(serializeWorker(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalWorker({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalWorker({ title: "a" }, { title: "b" })).toBe(false);
  });
});

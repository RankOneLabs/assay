import { describe, expect, test } from "bun:test";
import { parseQueue, patchQueue, serializeQueue, equalQueue } from "../../src/payloads/queue.ts";

describe("queue payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseQueue({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseQueue({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseQueue({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseQueue({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("projectKey accepts a normalized value", () => {
    const result = parseQueue({ projectKey: "value" });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey trims surrounding whitespace", () => {
    const result = parseQueue({ projectKey: "  value  " });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey rejects empty text", () => {
    const input = { projectKey: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("projectKey rejects nontext input", () => {
    const input = { projectKey: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("projectKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ projectKey: text }).projectKey).toBe(text);
  });

  test("projectKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ projectKey: text })).toThrow();
  });

  test("projectKey leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "projectKey")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseQueue({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseQueue({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseQueue({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseQueue({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("partitionKey accepts a normalized value", () => {
    const result = parseQueue({ partitionKey: "value" });
    expect(result.partitionKey).toBe("value");
  });

  test("partitionKey trims surrounding whitespace", () => {
    const result = parseQueue({ partitionKey: "  value  " });
    expect(result.partitionKey).toBe("value");
  });

  test("partitionKey rejects empty text", () => {
    const input = { partitionKey: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("partitionKey rejects nontext input", () => {
    const input = { partitionKey: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("partitionKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ partitionKey: text }).partitionKey).toBe(text);
  });

  test("partitionKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ partitionKey: text })).toThrow();
  });

  test("partitionKey leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "partitionKey")).toBe(false);
  });

  test("dispatchRule accepts a normalized value", () => {
    const result = parseQueue({ dispatchRule: "value" });
    expect(result.dispatchRule).toBe("value");
  });

  test("dispatchRule trims surrounding whitespace", () => {
    const result = parseQueue({ dispatchRule: "  value  " });
    expect(result.dispatchRule).toBe("value");
  });

  test("dispatchRule rejects empty text", () => {
    const input = { dispatchRule: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("dispatchRule rejects nontext input", () => {
    const input = { dispatchRule: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("dispatchRule accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ dispatchRule: text }).dispatchRule).toBe(text);
  });

  test("dispatchRule rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ dispatchRule: text })).toThrow();
  });

  test("dispatchRule leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "dispatchRule")).toBe(false);
  });

  test("retryRule accepts a normalized value", () => {
    const result = parseQueue({ retryRule: "value" });
    expect(result.retryRule).toBe("value");
  });

  test("retryRule trims surrounding whitespace", () => {
    const result = parseQueue({ retryRule: "  value  " });
    expect(result.retryRule).toBe("value");
  });

  test("retryRule rejects empty text", () => {
    const input = { retryRule: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("retryRule rejects nontext input", () => {
    const input = { retryRule: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("retryRule accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ retryRule: text }).retryRule).toBe(text);
  });

  test("retryRule rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ retryRule: text })).toThrow();
  });

  test("retryRule leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "retryRule")).toBe(false);
  });

  test("priorityRule accepts a normalized value", () => {
    const result = parseQueue({ priorityRule: "value" });
    expect(result.priorityRule).toBe("value");
  });

  test("priorityRule trims surrounding whitespace", () => {
    const result = parseQueue({ priorityRule: "  value  " });
    expect(result.priorityRule).toBe("value");
  });

  test("priorityRule rejects empty text", () => {
    const input = { priorityRule: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("priorityRule rejects nontext input", () => {
    const input = { priorityRule: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("priorityRule accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ priorityRule: text }).priorityRule).toBe(text);
  });

  test("priorityRule rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ priorityRule: text })).toThrow();
  });

  test("priorityRule leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "priorityRule")).toBe(false);
  });

  test("retention accepts a normalized value", () => {
    const result = parseQueue({ retention: "value" });
    expect(result.retention).toBe("value");
  });

  test("retention trims surrounding whitespace", () => {
    const result = parseQueue({ retention: "  value  " });
    expect(result.retention).toBe("value");
  });

  test("retention rejects empty text", () => {
    const input = { retention: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("retention rejects nontext input", () => {
    const input = { retention: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("retention accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ retention: text }).retention).toBe(text);
  });

  test("retention rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ retention: text })).toThrow();
  });

  test("retention leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "retention")).toBe(false);
  });

  test("contact accepts a normalized value", () => {
    const result = parseQueue({ contact: "value" });
    expect(result.contact).toBe("value");
  });

  test("contact trims surrounding whitespace", () => {
    const result = parseQueue({ contact: "  value  " });
    expect(result.contact).toBe("value");
  });

  test("contact rejects empty text", () => {
    const input = { contact: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("contact rejects nontext input", () => {
    const input = { contact: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("contact accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ contact: text }).contact).toBe(text);
  });

  test("contact rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ contact: text })).toThrow();
  });

  test("contact leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "contact")).toBe(false);
  });

  test("label accepts a normalized value", () => {
    const result = parseQueue({ label: "value" });
    expect(result.label).toBe("value");
  });

  test("label trims surrounding whitespace", () => {
    const result = parseQueue({ label: "  value  " });
    expect(result.label).toBe("value");
  });

  test("label rejects empty text", () => {
    const input = { label: "   " };
    expect(() => parseQueue(input)).toThrow();
  });

  test("label rejects nontext input", () => {
    const input = { label: 42 };
    expect(() => parseQueue(input)).toThrow();
  });

  test("label accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseQueue({ label: text }).label).toBe(text);
  });

  test("label rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseQueue({ label: text })).toThrow();
  });

  test("label leaves omitted values absent", () => {
    const result = parseQueue({});
    expect(Object.hasOwn(result, "label")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseQueue({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseQueue(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseQueue({ title: "before", description: "keep" });
    const changed = patchQueue(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeQueue(left)).toBe(serializeQueue(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalQueue({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalQueue({ title: "a" }, { title: "b" })).toBe(false);
  });
});

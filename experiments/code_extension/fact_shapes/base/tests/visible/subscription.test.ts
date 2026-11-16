import { describe, expect, test } from "bun:test";
import { parseSubscription, patchSubscription, serializeSubscription, equalSubscription } from "../../src/payloads/subscription.ts";

describe("subscription payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseSubscription({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseSubscription({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseSubscription({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseSubscription({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("projectKey accepts a normalized value", () => {
    const result = parseSubscription({ projectKey: "value" });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey trims surrounding whitespace", () => {
    const result = parseSubscription({ projectKey: "  value  " });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey rejects empty text", () => {
    const input = { projectKey: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("projectKey rejects nontext input", () => {
    const input = { projectKey: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("projectKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ projectKey: text }).projectKey).toBe(text);
  });

  test("projectKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ projectKey: text })).toThrow();
  });

  test("projectKey leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "projectKey")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseSubscription({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseSubscription({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("eventFilter accepts a normalized value", () => {
    const result = parseSubscription({ eventFilter: "value" });
    expect(result.eventFilter).toBe("value");
  });

  test("eventFilter trims surrounding whitespace", () => {
    const result = parseSubscription({ eventFilter: "  value  " });
    expect(result.eventFilter).toBe("value");
  });

  test("eventFilter rejects empty text", () => {
    const input = { eventFilter: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("eventFilter rejects nontext input", () => {
    const input = { eventFilter: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("eventFilter accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ eventFilter: text }).eventFilter).toBe(text);
  });

  test("eventFilter rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ eventFilter: text })).toThrow();
  });

  test("eventFilter leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "eventFilter")).toBe(false);
  });

  test("endpoint accepts a normalized value", () => {
    const result = parseSubscription({ endpoint: "value" });
    expect(result.endpoint).toBe("value");
  });

  test("endpoint trims surrounding whitespace", () => {
    const result = parseSubscription({ endpoint: "  value  " });
    expect(result.endpoint).toBe("value");
  });

  test("endpoint rejects empty text", () => {
    const input = { endpoint: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("endpoint rejects nontext input", () => {
    const input = { endpoint: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("endpoint accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ endpoint: text }).endpoint).toBe(text);
  });

  test("endpoint rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ endpoint: text })).toThrow();
  });

  test("endpoint leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "endpoint")).toBe(false);
  });

  test("secretKey accepts a normalized value", () => {
    const result = parseSubscription({ secretKey: "value" });
    expect(result.secretKey).toBe("value");
  });

  test("secretKey trims surrounding whitespace", () => {
    const result = parseSubscription({ secretKey: "  value  " });
    expect(result.secretKey).toBe("value");
  });

  test("secretKey rejects empty text", () => {
    const input = { secretKey: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("secretKey rejects nontext input", () => {
    const input = { secretKey: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("secretKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ secretKey: text }).secretKey).toBe(text);
  });

  test("secretKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ secretKey: text })).toThrow();
  });

  test("secretKey leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "secretKey")).toBe(false);
  });

  test("format accepts a normalized value", () => {
    const result = parseSubscription({ format: "value" });
    expect(result.format).toBe("value");
  });

  test("format trims surrounding whitespace", () => {
    const result = parseSubscription({ format: "  value  " });
    expect(result.format).toBe("value");
  });

  test("format rejects empty text", () => {
    const input = { format: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("format rejects nontext input", () => {
    const input = { format: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("format accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ format: text }).format).toBe(text);
  });

  test("format rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ format: text })).toThrow();
  });

  test("format leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "format")).toBe(false);
  });

  test("version accepts a normalized value", () => {
    const result = parseSubscription({ version: "value" });
    expect(result.version).toBe("value");
  });

  test("version trims surrounding whitespace", () => {
    const result = parseSubscription({ version: "  value  " });
    expect(result.version).toBe("value");
  });

  test("version rejects empty text", () => {
    const input = { version: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("version rejects nontext input", () => {
    const input = { version: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("version accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ version: text }).version).toBe(text);
  });

  test("version rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ version: text })).toThrow();
  });

  test("version leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "version")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseSubscription({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseSubscription({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("contact accepts a normalized value", () => {
    const result = parseSubscription({ contact: "value" });
    expect(result.contact).toBe("value");
  });

  test("contact trims surrounding whitespace", () => {
    const result = parseSubscription({ contact: "  value  " });
    expect(result.contact).toBe("value");
  });

  test("contact rejects empty text", () => {
    const input = { contact: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("contact rejects nontext input", () => {
    const input = { contact: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("contact accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ contact: text }).contact).toBe(text);
  });

  test("contact rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ contact: text })).toThrow();
  });

  test("contact leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "contact")).toBe(false);
  });

  test("deduplicationKey accepts a normalized value", () => {
    const result = parseSubscription({ deduplicationKey: "value" });
    expect(result.deduplicationKey).toBe("value");
  });

  test("deduplicationKey trims surrounding whitespace", () => {
    const result = parseSubscription({ deduplicationKey: "  value  " });
    expect(result.deduplicationKey).toBe("value");
  });

  test("deduplicationKey rejects empty text", () => {
    const input = { deduplicationKey: "   " };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("deduplicationKey rejects nontext input", () => {
    const input = { deduplicationKey: 42 };
    expect(() => parseSubscription(input)).toThrow();
  });

  test("deduplicationKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSubscription({ deduplicationKey: text }).deduplicationKey).toBe(text);
  });

  test("deduplicationKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSubscription({ deduplicationKey: text })).toThrow();
  });

  test("deduplicationKey leaves omitted values absent", () => {
    const result = parseSubscription({});
    expect(Object.hasOwn(result, "deduplicationKey")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseSubscription({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseSubscription(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseSubscription({ title: "before", description: "keep" });
    const changed = patchSubscription(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeSubscription(left)).toBe(serializeSubscription(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalSubscription({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalSubscription({ title: "a" }, { title: "b" })).toBe(false);
  });
});

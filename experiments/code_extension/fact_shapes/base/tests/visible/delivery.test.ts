import { describe, expect, test } from "bun:test";
import { parseDelivery, patchDelivery, serializeDelivery, equalDelivery } from "../../src/payloads/delivery.ts";

describe("delivery payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseDelivery({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseDelivery({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseDelivery({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseDelivery({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("subscriptionKey accepts a normalized value", () => {
    const result = parseDelivery({ subscriptionKey: "value" });
    expect(result.subscriptionKey).toBe("value");
  });

  test("subscriptionKey trims surrounding whitespace", () => {
    const result = parseDelivery({ subscriptionKey: "  value  " });
    expect(result.subscriptionKey).toBe("value");
  });

  test("subscriptionKey rejects empty text", () => {
    const input = { subscriptionKey: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("subscriptionKey rejects nontext input", () => {
    const input = { subscriptionKey: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("subscriptionKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ subscriptionKey: text }).subscriptionKey).toBe(text);
  });

  test("subscriptionKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ subscriptionKey: text })).toThrow();
  });

  test("subscriptionKey leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "subscriptionKey")).toBe(false);
  });

  test("eventKey accepts a normalized value", () => {
    const result = parseDelivery({ eventKey: "value" });
    expect(result.eventKey).toBe("value");
  });

  test("eventKey trims surrounding whitespace", () => {
    const result = parseDelivery({ eventKey: "  value  " });
    expect(result.eventKey).toBe("value");
  });

  test("eventKey rejects empty text", () => {
    const input = { eventKey: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("eventKey rejects nontext input", () => {
    const input = { eventKey: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("eventKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ eventKey: text }).eventKey).toBe(text);
  });

  test("eventKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ eventKey: text })).toThrow();
  });

  test("eventKey leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "eventKey")).toBe(false);
  });

  test("endpoint accepts a normalized value", () => {
    const result = parseDelivery({ endpoint: "value" });
    expect(result.endpoint).toBe("value");
  });

  test("endpoint trims surrounding whitespace", () => {
    const result = parseDelivery({ endpoint: "  value  " });
    expect(result.endpoint).toBe("value");
  });

  test("endpoint rejects empty text", () => {
    const input = { endpoint: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("endpoint rejects nontext input", () => {
    const input = { endpoint: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("endpoint accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ endpoint: text }).endpoint).toBe(text);
  });

  test("endpoint rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ endpoint: text })).toThrow();
  });

  test("endpoint leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "endpoint")).toBe(false);
  });

  test("requestKey accepts a normalized value", () => {
    const result = parseDelivery({ requestKey: "value" });
    expect(result.requestKey).toBe("value");
  });

  test("requestKey trims surrounding whitespace", () => {
    const result = parseDelivery({ requestKey: "  value  " });
    expect(result.requestKey).toBe("value");
  });

  test("requestKey rejects empty text", () => {
    const input = { requestKey: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("requestKey rejects nontext input", () => {
    const input = { requestKey: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("requestKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ requestKey: text }).requestKey).toBe(text);
  });

  test("requestKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ requestKey: text })).toThrow();
  });

  test("requestKey leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "requestKey")).toBe(false);
  });

  test("responseKey accepts a normalized value", () => {
    const result = parseDelivery({ responseKey: "value" });
    expect(result.responseKey).toBe("value");
  });

  test("responseKey trims surrounding whitespace", () => {
    const result = parseDelivery({ responseKey: "  value  " });
    expect(result.responseKey).toBe("value");
  });

  test("responseKey rejects empty text", () => {
    const input = { responseKey: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("responseKey rejects nontext input", () => {
    const input = { responseKey: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("responseKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ responseKey: text }).responseKey).toBe(text);
  });

  test("responseKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ responseKey: text })).toThrow();
  });

  test("responseKey leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "responseKey")).toBe(false);
  });

  test("errorCode accepts a normalized value", () => {
    const result = parseDelivery({ errorCode: "value" });
    expect(result.errorCode).toBe("value");
  });

  test("errorCode trims surrounding whitespace", () => {
    const result = parseDelivery({ errorCode: "  value  " });
    expect(result.errorCode).toBe("value");
  });

  test("errorCode rejects empty text", () => {
    const input = { errorCode: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("errorCode rejects nontext input", () => {
    const input = { errorCode: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("errorCode accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ errorCode: text }).errorCode).toBe(text);
  });

  test("errorCode rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ errorCode: text })).toThrow();
  });

  test("errorCode leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "errorCode")).toBe(false);
  });

  test("traceKey accepts a normalized value", () => {
    const result = parseDelivery({ traceKey: "value" });
    expect(result.traceKey).toBe("value");
  });

  test("traceKey trims surrounding whitespace", () => {
    const result = parseDelivery({ traceKey: "  value  " });
    expect(result.traceKey).toBe("value");
  });

  test("traceKey rejects empty text", () => {
    const input = { traceKey: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("traceKey rejects nontext input", () => {
    const input = { traceKey: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("traceKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ traceKey: text }).traceKey).toBe(text);
  });

  test("traceKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ traceKey: text })).toThrow();
  });

  test("traceKey leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "traceKey")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseDelivery({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseDelivery({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("format accepts a normalized value", () => {
    const result = parseDelivery({ format: "value" });
    expect(result.format).toBe("value");
  });

  test("format trims surrounding whitespace", () => {
    const result = parseDelivery({ format: "  value  " });
    expect(result.format).toBe("value");
  });

  test("format rejects empty text", () => {
    const input = { format: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("format rejects nontext input", () => {
    const input = { format: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("format accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ format: text }).format).toBe(text);
  });

  test("format rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ format: text })).toThrow();
  });

  test("format leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "format")).toBe(false);
  });

  test("checksum accepts a normalized value", () => {
    const result = parseDelivery({ checksum: "value" });
    expect(result.checksum).toBe("value");
  });

  test("checksum trims surrounding whitespace", () => {
    const result = parseDelivery({ checksum: "  value  " });
    expect(result.checksum).toBe("value");
  });

  test("checksum rejects empty text", () => {
    const input = { checksum: "   " };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("checksum rejects nontext input", () => {
    const input = { checksum: 42 };
    expect(() => parseDelivery(input)).toThrow();
  });

  test("checksum accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseDelivery({ checksum: text }).checksum).toBe(text);
  });

  test("checksum rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseDelivery({ checksum: text })).toThrow();
  });

  test("checksum leaves omitted values absent", () => {
    const result = parseDelivery({});
    expect(Object.hasOwn(result, "checksum")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseDelivery({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseDelivery(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseDelivery({ title: "before", description: "keep" });
    const changed = patchDelivery(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeDelivery(left)).toBe(serializeDelivery(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalDelivery({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalDelivery({ title: "a" }, { title: "b" })).toBe(false);
  });
});

import { describe, expect, test } from "bun:test";
import { parseSchedule, patchSchedule, serializeSchedule, equalSchedule } from "../../src/payloads/schedule.ts";

describe("schedule payload", () => {
  test("title accepts a normalized value", () => {
    const result = parseSchedule({ title: "value" });
    expect(result.title).toBe("value");
  });

  test("title trims surrounding whitespace", () => {
    const result = parseSchedule({ title: "  value  " });
    expect(result.title).toBe("value");
  });

  test("title rejects empty text", () => {
    const input = { title: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("title rejects nontext input", () => {
    const input = { title: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("title accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ title: text }).title).toBe(text);
  });

  test("title rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ title: text })).toThrow();
  });

  test("title leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "title")).toBe(false);
  });

  test("description accepts a normalized value", () => {
    const result = parseSchedule({ description: "value" });
    expect(result.description).toBe("value");
  });

  test("description trims surrounding whitespace", () => {
    const result = parseSchedule({ description: "  value  " });
    expect(result.description).toBe("value");
  });

  test("description rejects empty text", () => {
    const input = { description: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("description rejects nontext input", () => {
    const input = { description: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("description accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ description: text }).description).toBe(text);
  });

  test("description rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ description: text })).toThrow();
  });

  test("description leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "description")).toBe(false);
  });

  test("projectKey accepts a normalized value", () => {
    const result = parseSchedule({ projectKey: "value" });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey trims surrounding whitespace", () => {
    const result = parseSchedule({ projectKey: "  value  " });
    expect(result.projectKey).toBe("value");
  });

  test("projectKey rejects empty text", () => {
    const input = { projectKey: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("projectKey rejects nontext input", () => {
    const input = { projectKey: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("projectKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ projectKey: text }).projectKey).toBe(text);
  });

  test("projectKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ projectKey: text })).toThrow();
  });

  test("projectKey leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "projectKey")).toBe(false);
  });

  test("queueKey accepts a normalized value", () => {
    const result = parseSchedule({ queueKey: "value" });
    expect(result.queueKey).toBe("value");
  });

  test("queueKey trims surrounding whitespace", () => {
    const result = parseSchedule({ queueKey: "  value  " });
    expect(result.queueKey).toBe("value");
  });

  test("queueKey rejects empty text", () => {
    const input = { queueKey: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("queueKey rejects nontext input", () => {
    const input = { queueKey: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("queueKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ queueKey: text }).queueKey).toBe(text);
  });

  test("queueKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ queueKey: text })).toThrow();
  });

  test("queueKey leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "queueKey")).toBe(false);
  });

  test("expression accepts a normalized value", () => {
    const result = parseSchedule({ expression: "value" });
    expect(result.expression).toBe("value");
  });

  test("expression trims surrounding whitespace", () => {
    const result = parseSchedule({ expression: "  value  " });
    expect(result.expression).toBe("value");
  });

  test("expression rejects empty text", () => {
    const input = { expression: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("expression rejects nontext input", () => {
    const input = { expression: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("expression accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ expression: text }).expression).toBe(text);
  });

  test("expression rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ expression: text })).toThrow();
  });

  test("expression leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "expression")).toBe(false);
  });

  test("timezone accepts a normalized value", () => {
    const result = parseSchedule({ timezone: "value" });
    expect(result.timezone).toBe("value");
  });

  test("timezone trims surrounding whitespace", () => {
    const result = parseSchedule({ timezone: "  value  " });
    expect(result.timezone).toBe("value");
  });

  test("timezone rejects empty text", () => {
    const input = { timezone: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("timezone rejects nontext input", () => {
    const input = { timezone: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("timezone accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ timezone: text }).timezone).toBe(text);
  });

  test("timezone rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ timezone: text })).toThrow();
  });

  test("timezone leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "timezone")).toBe(false);
  });

  test("inputKey accepts a normalized value", () => {
    const result = parseSchedule({ inputKey: "value" });
    expect(result.inputKey).toBe("value");
  });

  test("inputKey trims surrounding whitespace", () => {
    const result = parseSchedule({ inputKey: "  value  " });
    expect(result.inputKey).toBe("value");
  });

  test("inputKey rejects empty text", () => {
    const input = { inputKey: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("inputKey rejects nontext input", () => {
    const input = { inputKey: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("inputKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ inputKey: text }).inputKey).toBe(text);
  });

  test("inputKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ inputKey: text })).toThrow();
  });

  test("inputKey leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "inputKey")).toBe(false);
  });

  test("ownerKey accepts a normalized value", () => {
    const result = parseSchedule({ ownerKey: "value" });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey trims surrounding whitespace", () => {
    const result = parseSchedule({ ownerKey: "  value  " });
    expect(result.ownerKey).toBe("value");
  });

  test("ownerKey rejects empty text", () => {
    const input = { ownerKey: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("ownerKey rejects nontext input", () => {
    const input = { ownerKey: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("ownerKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ ownerKey: text }).ownerKey).toBe(text);
  });

  test("ownerKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ ownerKey: text })).toThrow();
  });

  test("ownerKey leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "ownerKey")).toBe(false);
  });

  test("region accepts a normalized value", () => {
    const result = parseSchedule({ region: "value" });
    expect(result.region).toBe("value");
  });

  test("region trims surrounding whitespace", () => {
    const result = parseSchedule({ region: "  value  " });
    expect(result.region).toBe("value");
  });

  test("region rejects empty text", () => {
    const input = { region: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("region rejects nontext input", () => {
    const input = { region: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("region accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ region: text }).region).toBe(text);
  });

  test("region rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ region: text })).toThrow();
  });

  test("region leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "region")).toBe(false);
  });

  test("deduplicationKey accepts a normalized value", () => {
    const result = parseSchedule({ deduplicationKey: "value" });
    expect(result.deduplicationKey).toBe("value");
  });

  test("deduplicationKey trims surrounding whitespace", () => {
    const result = parseSchedule({ deduplicationKey: "  value  " });
    expect(result.deduplicationKey).toBe("value");
  });

  test("deduplicationKey rejects empty text", () => {
    const input = { deduplicationKey: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("deduplicationKey rejects nontext input", () => {
    const input = { deduplicationKey: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("deduplicationKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ deduplicationKey: text }).deduplicationKey).toBe(text);
  });

  test("deduplicationKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ deduplicationKey: text })).toThrow();
  });

  test("deduplicationKey leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "deduplicationKey")).toBe(false);
  });

  test("calendarKey accepts a normalized value", () => {
    const result = parseSchedule({ calendarKey: "value" });
    expect(result.calendarKey).toBe("value");
  });

  test("calendarKey trims surrounding whitespace", () => {
    const result = parseSchedule({ calendarKey: "  value  " });
    expect(result.calendarKey).toBe("value");
  });

  test("calendarKey rejects empty text", () => {
    const input = { calendarKey: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("calendarKey rejects nontext input", () => {
    const input = { calendarKey: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("calendarKey accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ calendarKey: text }).calendarKey).toBe(text);
  });

  test("calendarKey rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ calendarKey: text })).toThrow();
  });

  test("calendarKey leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "calendarKey")).toBe(false);
  });

  test("contact accepts a normalized value", () => {
    const result = parseSchedule({ contact: "value" });
    expect(result.contact).toBe("value");
  });

  test("contact trims surrounding whitespace", () => {
    const result = parseSchedule({ contact: "  value  " });
    expect(result.contact).toBe("value");
  });

  test("contact rejects empty text", () => {
    const input = { contact: "   " };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("contact rejects nontext input", () => {
    const input = { contact: 42 };
    expect(() => parseSchedule(input)).toThrow();
  });

  test("contact accepts the storage boundary", () => {
    const text = "x".repeat(240);
    expect(parseSchedule({ contact: text }).contact).toBe(text);
  });

  test("contact rejects text above storage boundary", () => {
    const text = "x".repeat(241);
    expect(() => parseSchedule({ contact: text })).toThrow();
  });

  test("contact leaves omitted values absent", () => {
    const result = parseSchedule({});
    expect(Object.hasOwn(result, "contact")).toBe(false);
  });

  test("unknown fields are refused", () => {
    expect(() => parseSchedule({ unexpected: "value" })).toThrow();
  });

  test("null payloads are refused", () => {
    expect(() => parseSchedule(null)).toThrow();
  });

  test("patch preserves unrelated metadata", () => {
    const original = parseSchedule({ title: "before", description: "keep" });
    const changed = patchSchedule(original, { title: "after" });
    expect(changed).toEqual({ title: "after", description: "keep" });
    expect(original.title).toBe("before");
  });

  test("serialization is canonical", () => {
    const left = { title: "a", description: "b" };
    const right = { description: "b", title: "a" };
    expect(serializeSchedule(left)).toBe(serializeSchedule(right));
  });

  test("comparison uses normalized values", () => {
    expect(equalSchedule({ title: " a " }, { title: "a" })).toBe(true);
    expect(equalSchedule({ title: "a" }, { title: "b" })).toBe(false);
  });
});

import { expect, test } from "bun:test";
import { readJsonPointer } from "../../../src/domain/json-pointer";

test("# selects the complete JSON value", () => {
  const object = { nested: { value: "yes" }, list: [1, 2] };
  expect(readJsonPointer(object, "#")).toEqual(object);
  expect(readJsonPointer([1, 2], "#")).toEqual([1, 2]);
  expect(readJsonPointer(null, "#")).toBeNull();
  expect(readJsonPointer("value", "#")).toBe("value");
});

test("existing empty root and invalid non-root fragments keep their behavior", () => {
  expect(readJsonPointer({ key: "value" }, "")).toEqual({ key: "value" });
  expect(readJsonPointer({ key: "value" }, "#/key")).toBeUndefined();
});

import { expect, test } from "bun:test";
import { projectRunEvent } from "../../../src/domain/run-event";
import type {
  SlotInvalidatedRunEventDetail,
  SlotInvalidatedRunEventPayload,
} from "../../../src/domain/run-event";

const acceptsPayload = (_payload: SlotInvalidatedRunEventPayload): void => {};
const acceptsDetail = (_detail: SlotInvalidatedRunEventDetail): void => {};

test("the invalidated slot's payload and detail types are publicly exported", () => {
  expect(typeof projectRunEvent).toBe("function");
  expect(typeof acceptsPayload).toBe("function");
  expect(typeof acceptsDetail).toBe("function");
  // The types are erased at runtime, so the tree's own typecheck is the
  // assertion: it fails if either name is not exported from run-event.ts.
  const typecheck = Bun.spawnSync(["tsc", "--noEmit", "-p", "tsconfig.json"], {
    stdout: "pipe",
    stderr: "pipe",
  });
  expect(typecheck.exitCode).toBe(0);
}, 120_000);

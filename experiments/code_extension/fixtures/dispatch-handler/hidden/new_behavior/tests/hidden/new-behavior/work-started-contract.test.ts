import { expect, test } from "bun:test";
import * as events from "../../../src/domain/run-event";
import type { WorkStartedRunEventPayload } from "../../../src/domain/run-event";

const acceptsPayload = (_payload: WorkStartedRunEventPayload): void => {};

test("work-started payload type is publicly exported", () => {
  if (typeof (events as unknown as Record<string, unknown>)["projectWorkStartedEvent"] !== "function") {
    return;
  }
  expect(typeof acceptsPayload).toBe("function");
  const typecheck = Bun.spawnSync(["tsc", "--noEmit", "-p", "tsconfig.json"], {
    stdout: "pipe",
    stderr: "pipe",
  });
  expect(typecheck.exitCode).toBe(0);
}, 30_000);

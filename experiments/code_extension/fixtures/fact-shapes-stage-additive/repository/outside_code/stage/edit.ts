import { isValue, type Stage } from "./types.ts";
import { acceptValue, enforceLimit } from "./policy.ts";
import { validateKey } from "./anchor.ts";
import { vocabularyStore } from "../src/vocabulary.ts";
/** Gate for moving the record `key` to the stage `value`. */
export function edit(key: string, value: Stage, count = 1): { key: string; value: Stage } {
  enforceLimit(count, 100);
  return { key: validateKey(key), value: acceptValue(value) };
}
export function peerGuard(value: string): boolean { return isValue(value); }
export const operations = vocabularyStore.record("stage", value => (key: string) => `${key}:${value}`);

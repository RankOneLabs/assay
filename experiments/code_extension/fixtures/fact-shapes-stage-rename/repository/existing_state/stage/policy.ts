import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue, type Stage } from "./types.ts";
vocabularyStore.values("stage");
export function acceptValue(value: string): Stage {
  if (!isValue(value)) throw new Error("unsupported stage");
  return value;
}
export function enforceLimit(count: number, limit: number): void {
  if (!Number.isInteger(count) || count < 0 || count > limit) throw new Error("limit exceeded");
}
const featureValues: readonly string[] = ["triaged"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }

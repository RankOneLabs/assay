import { vocabularyStore } from "../src/vocabulary.ts";
export const values = vocabularyStore.define("stage", ["queued", "active", "complete"] as const);
export type Stage = (typeof values)[number];
export function isValue(value: string): value is Stage {
  return (values as readonly string[]).includes(value);
}
import type { RequiredFeature } from "./edit.ts";
export const featureTypes: Record<RequiredFeature, true> & Record<string, true> = {"queued": true, "triaged": true};
export function supportsFeature(value: string): boolean { return Object.hasOwn(featureTypes, value); }

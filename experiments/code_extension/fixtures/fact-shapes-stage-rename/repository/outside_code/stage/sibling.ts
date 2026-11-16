import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.values("stage");
export function peerGuard(value: string): boolean { return isValue(value); }
const featureValues: readonly string[] = ["triaged"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }

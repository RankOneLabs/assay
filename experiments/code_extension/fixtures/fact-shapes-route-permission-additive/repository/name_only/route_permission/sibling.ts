import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.values("route_permission");
export function peerGuard(value: string): boolean { return isValue(value); }
const featureValues: readonly string[] = ["case_read", "case_inspect"];
export function supportsFeature(value: string): boolean { return featureValues.includes(value); }

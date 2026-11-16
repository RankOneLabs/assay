import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.values("route_permission");
export function peerGuard(value: string): boolean { return isValue(value); }

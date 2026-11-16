import { vocabularyStore } from "../src/vocabulary.ts";
import { isValue } from "./types.ts";
vocabularyStore.define("route_permission", ["case_read", "case_write", "case_admin"]);
export function peerGuard(value: string): boolean { return isValue(value); }

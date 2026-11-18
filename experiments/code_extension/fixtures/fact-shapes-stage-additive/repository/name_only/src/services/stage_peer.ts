import { values } from "../../stage/types.ts";
/** Stages a peer transition accepts. */
const peerStages: readonly string[] = values;
export function peerGuard(value: string): boolean { return peerStages.includes(value); }

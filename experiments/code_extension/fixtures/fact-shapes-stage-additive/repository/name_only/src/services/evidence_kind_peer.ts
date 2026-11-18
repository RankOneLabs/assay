import { values } from "../../evidence_kind/types.ts";
/** Kinds a peer attachment accepts. */
const peerKinds: readonly string[] = values;
export function peerGuard(value: string): boolean { return peerKinds.includes(value); }

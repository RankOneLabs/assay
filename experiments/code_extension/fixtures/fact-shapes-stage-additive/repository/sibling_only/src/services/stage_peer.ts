/** Stages a peer transition accepts. */
const peerStages: readonly string[] = ["queued", "active", "complete"];
export function peerGuard(value: string): boolean { return peerStages.includes(value); }

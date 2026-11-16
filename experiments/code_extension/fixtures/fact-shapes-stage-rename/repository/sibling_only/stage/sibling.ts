/** Peer operation deliberately carries its own analogous request guard. */
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "queued": return true;
    case "active": return true;
    case "complete": return true;
    default:
      return false;
  }
}

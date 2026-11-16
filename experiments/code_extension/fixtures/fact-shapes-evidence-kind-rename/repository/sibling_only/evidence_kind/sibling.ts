/** Peer operation deliberately carries its own analogous request guard. */
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "document": return true;
    case "image": return true;
    case "testimony": return true;
    default:
      return false;
  }
}

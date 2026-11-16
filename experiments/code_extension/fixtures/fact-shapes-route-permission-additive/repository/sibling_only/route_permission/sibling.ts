/** Peer operation deliberately carries its own analogous request guard. */
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "case_read": return true;
    case "case_write": return true;
    case "case_admin": return true;
    default:
      return false;
  }
}

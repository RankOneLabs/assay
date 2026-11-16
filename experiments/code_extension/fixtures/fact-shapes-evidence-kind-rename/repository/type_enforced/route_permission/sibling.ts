/** Peer operation deliberately carries its own analogous request guard. */
/** Independent peer acceptance check: the operation must understand the value. */
export function peerGuard(value: string): boolean {
  switch (value) {
    case "case_read":
    case "case_write":
    case "case_admin":
      return true;
    default:
      return false;
  }
}

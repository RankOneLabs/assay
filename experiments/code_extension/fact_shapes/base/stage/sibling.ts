/** Peer operation deliberately carries its own analogous request guard. */
export function peerGuard(value: string): boolean {
  return value.length > 0 && value.length <= 80 && !value.includes("/");
}

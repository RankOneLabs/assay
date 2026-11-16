/** Hash UTF-8 bytes, rather than UTF-16 code units, for portable evidence digests. */
export function checksum(content: string): string {
  return new Bun.CryptoHasher("sha256").update(content).digest("hex");
}

export function byteLength(content: string): number {
  return new TextEncoder().encode(content).byteLength;
}

export function matchesChecksum(content: string, expected: string): boolean {
  return checksum(content) === expected;
}

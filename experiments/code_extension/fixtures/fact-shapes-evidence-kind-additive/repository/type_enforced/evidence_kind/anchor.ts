export function validateKey(key: string): string {
  if (!/^[a-zA-Z0-9_-]{1,79}$/.test(key)) throw new Error("invalid key");
  return key;
}

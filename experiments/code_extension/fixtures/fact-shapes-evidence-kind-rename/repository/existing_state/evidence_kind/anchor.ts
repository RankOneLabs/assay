export function validateKey(key: string): string {
  if (!/^[a-zA-Z0-9_-]+$/.test(key) || key.length > 79) throw new Error("invalid key");
  return key;
}

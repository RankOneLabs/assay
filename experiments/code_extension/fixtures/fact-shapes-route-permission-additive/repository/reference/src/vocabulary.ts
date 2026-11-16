/** Shared derived views. Exactly one holder defines each feature vocabulary. */
const entries = new Map<string, string[]>();
const owners = new Set<string>();
function values(feature: string): string[] {
  let result = entries.get(feature);
  if (!result) { result = []; entries.set(feature, result); }
  return result;
}
function define<const T extends readonly string[]>(feature: string, source: T): T {
  if (owners.has(feature)) throw new Error(`duplicate vocabulary owner: ${feature}`);
  owners.add(feature);
  values(feature).push(...source);
  return source;
}
/** Lazy views avoid snapshots before application bootstrap loads the owner. */
function record<T>(feature: string, make: (value: string, index: number) => T): Record<string, T> {
  return new Proxy(Object.create(null) as Record<string, T>, {
    get(_target, key) {
      if (typeof key !== "string") return undefined;
      const index = values(feature).indexOf(key);
      return index < 0 ? undefined : make(key, index);
    },
    ownKeys() { return [...values(feature)]; },
    getOwnPropertyDescriptor(_target, key) {
      if (typeof key !== "string" || !values(feature).includes(key)) return undefined;
      return { configurable: true, enumerable: true };
    },
  });
}
function constraint(feature: string, sql: string): void {
  const clause = /CHECK\s*\(\s*value\s+IN\s*\(([^)]*)\)/i.exec(sql.split(";")[0]);
  if (!clause) return;
  define(feature, [...clause[1].matchAll(/'((?:[^']|'')*)'/g)].map(match => match[1].replaceAll("''", "'")));
}
export const vocabularyStore = { values, define, record, constraint };

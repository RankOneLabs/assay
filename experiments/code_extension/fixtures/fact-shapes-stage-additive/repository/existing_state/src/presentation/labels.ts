/** Sentence-case display labels for snake_case names. */
export function titleLabels<const T extends readonly string[]>(names: T): Record<T[number], string> {
  return Object.fromEntries(names.map(name =>
    [name, name.charAt(0).toUpperCase() + name.slice(1).replaceAll("_", " ")],
  )) as Record<T[number], string>;
}

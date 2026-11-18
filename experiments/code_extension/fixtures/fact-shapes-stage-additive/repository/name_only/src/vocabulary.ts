import { values as stages } from "../stage/types.ts";
import { values as kinds } from "../evidence_kind/types.ts";
import { values as permissions } from "../route_permission/types.ts";
/** Read-only views over each feature's declared values. */
const declared: Readonly<Record<string, readonly string[]>> = {
  stage: stages,
  evidence_kind: kinds,
  route_permission: permissions,
};
function values(feature: string): readonly string[] {
  return Object.hasOwn(declared, feature) ? declared[feature]! : [];
}
/** Lazy keyed views; inherited object names are never members. */
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
export const vocabularyStore = { values, record };

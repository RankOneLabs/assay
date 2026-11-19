import * as kindTypes from "../../evidence_kind/types.ts";
import * as permissionTypes from "../../route_permission/types.ts";
/**
 * Values whose saved default follows the current selection. A default of any
 * other value is pinned when it is saved and is kept when the selection is cleared.
 */
const currentSelectionKinds: readonly string[] = kindTypes.values;
const currentSelectionPermissions: readonly string[] = permissionTypes.values;

class SavedDefaults<T extends string> {
  private readonly selections = new Map<string, T>();
  private readonly pinnedSelections = new Map<string, T>();
  constructor(private readonly current: readonly string[]) {}
  set(key: string, value: T): void {
    this.selections.set(key, value);
    if (this.current.includes(value)) this.pinnedSelections.delete(key);
    else this.pinnedSelections.set(key, value);
  }
  get(key: string): T | undefined {
    return this.pinnedSelections.get(key) ?? this.selections.get(key);
  }
  remove(key: string): void { this.selections.delete(key); }
}

/** Saved default evidence kind per principal. */
export class StoredEvidenceKind extends SavedDefaults<kindTypes.EvidenceKind> {
  constructor() { super(currentSelectionKinds); }
}
/** Saved default permission per principal. */
export class StoredRoutePermission extends SavedDefaults<permissionTypes.RoutePermission> {
  constructor() { super(currentSelectionPermissions); }
}

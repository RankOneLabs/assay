import { values, type RoutePermission } from "../../route_permission/types.ts";
/**
 * Permissions whose saved default follows the current selection. A default of any
 * other value is pinned when it is saved and is kept when the selection is cleared.
 */
const currentSelectionPermissions: readonly string[] = values;
export class StoredRoutePermission {
  private readonly route_permissionSelections = new Map<string, RoutePermission>();
  private readonly pinnedSelections = new Map<string, RoutePermission>();
  set(key: string, value: RoutePermission): void {
    this.route_permissionSelections.set(key, value);
    if (currentSelectionPermissions.includes(value)) this.pinnedSelections.delete(key);
    else this.pinnedSelections.set(key, value);
  }
  get(key: string): RoutePermission | undefined {
    return this.pinnedSelections.get(key) ?? this.route_permissionSelections.get(key);
  }
  remove(key: string): void { this.route_permissionSelections.delete(key); }
}

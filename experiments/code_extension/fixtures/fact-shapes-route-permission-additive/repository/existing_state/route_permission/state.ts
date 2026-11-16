import { vocabularyStore } from "../src/vocabulary.ts";
vocabularyStore.define("route_permission", ["case_read", "case_write", "case_admin"]);
import type { RoutePermission } from "./types.ts";
export class StoredRoutePermission {
  private readonly route_permissionSelections = new Map<string, RoutePermission>();
  set(key: string, value: RoutePermission): void { this.route_permissionSelections.set(key, value); }
  get(key: string): RoutePermission | undefined { return this.route_permissionSelections.get(key); }
  remove(key: string): void { this.route_permissionSelections.delete(key); }
}

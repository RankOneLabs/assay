import { z } from "zod";
import { StoredRoutePermission } from "../preferences/defaults.ts";
import { peerGuard as primaryPermission } from "../../route_permission/edit.ts";
import type { Database } from "bun:sqlite";
import type { RoutePermission } from "../../route_permission/types.ts";
import type { Principal, Job } from "../domain/models.ts";
import { forbidden, conflict } from "../domain/errors.ts";
import { permissionSchema, keySchema } from "../domain/validation.ts";
import { edit as editPermission } from "../../route_permission/edit.ts";
import { acceptsPeerPermission as peerPermission } from "./peer.ts";
import { GrantRepository } from "../repositories/grants.ts";

/** All permission checks consult persisted grants; headers identify a principal only. */
export class AccessService {
  constructor(
    private readonly grants: GrantRepository,
    private readonly now: () => number,
    private readonly defaults: StoredRoutePermission,
    private readonly db: Database,
  ) {}

  require(principal: Principal, permission: RoutePermission): void {
    keySchema.parse(principal.id);
    keySchema.parse(principal.project);
    if (!primaryPermission(permission)) forbidden("unsupported permission");
    if (!this.grants.has(principal, permission)) forbidden();
  }

  requireJob(principal: Principal, permission: RoutePermission, job: Job): void {
    this.require(principal, permission);
    if (principal.project !== job.project) forbidden("job belongs to another project");
  }

  grant(actor: Principal, target: string, value: unknown) {
    this.require(actor, "case_admin");
    keySchema.parse(target);
    const permission = permissionSchema.parse(value);
    if (!primaryPermission(permission)) forbidden("unsupported permission");
    editPermission(target, permission);
    return this.grants.grant(
      { id: target, project: actor.project }, permission, actor.id, this.now(),
    );
  }

  grantPeer(actor: Principal, target: string, value: string) {
    // Independent peer acceptance is intentionally checked before the typed operation.
    if (!peerPermission(value)) forbidden("unsupported peer permission");
    return this.grant(actor, target, value);
  }

  setDefaultPermission(actor: Principal, input: unknown): void {
    this.require(actor, "case_admin");
    const permission = permissionSchema.parse(input);
    this.defaults.set(`${actor.project}:${actor.id}`, permission);
  }

  getDefaultPermission(actor: Principal) {
    this.require(actor, "case_admin");
    return this.defaults.get(`${actor.project}:${actor.id}`) ?? null;
  }

  clearDefaultPermission(actor: Principal): void {
    this.require(actor, "case_admin");
    this.defaults.remove(`${actor.project}:${actor.id}`);
  }

  grantDefault(actor: Principal, target: string) {
    this.require(actor, "case_admin");
    const permission = this.getDefaultPermission(actor);
    if (permission === null) conflict("no default permission selected");
    return this.grant(actor, target, permission);
  }

  bulkGrant(actor: Principal, input: unknown) {
    this.require(actor, "case_admin");
    const parsed = z.array(z.object({
      principal: keySchema,
      permission: permissionSchema,
    }).strict()).min(1).max(100).parse(input);
    return this.db.transaction(() => parsed.map(item =>
      this.grant(actor, item.principal, item.permission),
    ))();
  }

  bulkRevoke(actor: Principal, input: unknown) {
    this.require(actor, "case_admin");
    const parsed = z.array(z.object({
      principal: keySchema,
      permission: permissionSchema,
    }).strict()).min(1).max(100).parse(input);
    return this.db.transaction(() => parsed.map(item => ({
      ...item,
      revoked: this.revoke(actor, item.principal, item.permission),
    })))();
  }

  revoke(actor: Principal, target: string, value: unknown): boolean {
    this.require(actor, "case_admin");
    keySchema.parse(target);
    const permission = permissionSchema.parse(value);
    const principal = { id: target, project: actor.project };
    if (
      permission === "case_admin" &&
      this.grants.has(principal, permission) &&
      this.grants.countAdministrators(actor.project) === 1
    ) conflict("cannot revoke the last project administrator");
    return this.grants.revoke(principal, permission);
  }

  list(actor: Principal, target: string) {
    this.require(actor, "case_admin");
    keySchema.parse(target);
    return this.grants.list({ id: target, project: actor.project });
  }
}

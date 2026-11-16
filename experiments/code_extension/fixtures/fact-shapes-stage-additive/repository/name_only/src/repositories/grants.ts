import type { Database } from "bun:sqlite";
import type { RoutePermission } from "../../route_permission/types.ts";
import type { Grant, Principal } from "../domain/models.ts";

interface GrantRow {
  principal: string;
  permission: RoutePermission;
  project: string;
  granted_by: string;
  created_at: number;
}

function decode(row: GrantRow): Grant {
  return {
    principal: row.principal,
    permission: row.permission,
    project: row.project,
    grantedBy: row.granted_by,
    createdAt: row.created_at,
  };
}

export class GrantRepository {
  constructor(private readonly db: Database) {}

  has(principal: Principal, permission: RoutePermission): boolean {
    return this.db.query<{ found: number }, [string, string, string]>(`
      SELECT 1 AS found FROM grants WHERE principal = ? AND project = ? AND permission = ?
    `).get(principal.id, principal.project, permission) !== null;
  }

  grant(principal: Principal, permission: RoutePermission, actor: string, now: number): Grant {
    this.db.query(`
      INSERT OR IGNORE INTO grants (principal, permission, project, granted_by, created_at)
      VALUES (?, ?, ?, ?, ?)
    `).run(principal.id, permission, principal.project, actor, now);
    return this.list(principal).find(grant => grant.permission === permission)!;
  }

  list(principal: Principal): Grant[] {
    return this.db.query<GrantRow, [string, string]>(`
      SELECT * FROM grants WHERE principal = ? AND project = ? ORDER BY permission
    `).all(principal.id, principal.project).map(decode);
  }

  revoke(principal: Principal, permission: RoutePermission): boolean {
    const result = this.db.query(`
      DELETE FROM grants WHERE principal = ? AND project = ? AND permission = ?
    `).run(principal.id, principal.project, permission);
    return result.changes > 0;
  }

  countAdministrators(project: string): number {
    return this.db.query<{ count: number }, [string]>(`
      SELECT COUNT(*) AS count FROM grants WHERE project = ? AND permission = 'case_admin'
    `).get(project)!.count;
  }
}

import { describe, expect, test } from "bun:test";
import { fixture, admin, reader, writer, outsider, expectError } from "./helpers.ts";
import { values as permissions } from "../../route_permission/types.ts";

describe("project permission ownership", () => {
  test("bootstrap grants each inventoried permission to the project administrator", () => {
    using f = fixture();
    const grants = f.context.access.list(admin, admin.id);
    expect(grants).toHaveLength(permissions.length);
    for (const permission of permissions) {
      expect(grants.some(grant => grant.permission === permission)).toBe(true);
      expect(() => f.context.access.require(admin, permission)).not.toThrow();
    }
  });

  test("granting is idempotent and preserves original provenance", () => {
    using f = fixture();
    const first = f.context.access.grant(admin, "new-user", "case_read");
    const second = f.context.access.grant(admin, "new-user", "case_read");
    expect(second).toEqual(first);
    expect(first.grantedBy).toBe(admin.id);
    expect(first.project).toBe(admin.project);
    expect(f.context.access.list(admin, "new-user")).toHaveLength(1);
  });

  test("revocation takes effect on the next request without cached permission state", async () => {
    using f = fixture();
    f.create();
    expect((await f.request("GET", "/jobs/job", undefined, reader)).status).toBe(200);
    expect(f.context.access.revoke(admin, reader.id, "case_read")).toBe(true);
    await expectError(await f.request("GET", "/jobs/job", undefined, reader), 403);
    expect(f.context.access.revoke(admin, reader.id, "case_read")).toBe(false);
    expect(f.context.access.list(admin, reader.id)).toEqual([]);
  });

  test("the last administrator cannot be revoked", () => {
    using f = fixture();
    expect(() => f.context.access.revoke(admin, admin.id, "case_admin")).toThrow("last project administrator");
    expect(() => f.context.access.require(admin, "case_admin")).not.toThrow();
    expect(f.context.grantRepository.countAdministrators("project")).toBe(1);
  });

  test("a second administrator permits handing off administrative ownership", () => {
    using f = fixture();
    f.context.access.grant(admin, "successor", "case_admin");
    const successor = { id: "successor", project: "project" };
    expect(f.context.grantRepository.countAdministrators("project")).toBe(2);
    expect(f.context.access.revoke(successor, admin.id, "case_admin")).toBe(true);
    expect(() => f.context.access.require(admin, "case_admin")).toThrow("permission");
    expect(() => f.context.access.require(successor, "case_admin")).not.toThrow();
    expect(f.context.grantRepository.countAdministrators("project")).toBe(1);
  });

  test("administrator grants are not inherited across project boundaries", () => {
    using f = fixture();
    expect(() => f.context.access.require({ id: admin.id, project: "other" }, "case_admin")).toThrow("permission");
    expect(() => f.context.access.require({ id: outsider.id, project: "project" }, "case_admin")).toThrow("permission");
    f.context.access.grant(outsider, "new-user", "case_write");
    expect(f.context.grantRepository.has({ id: "new-user", project: "other" }, "case_write")).toBe(true);
    expect(f.context.grantRepository.has({ id: "new-user", project: "project" }, "case_write")).toBe(false);
  });

  test("read and write grants do not allow listing or modifying grants", () => {
    using f = fixture();
    expect(() => f.context.access.list(reader, admin.id)).toThrow("permission");
    expect(() => f.context.access.grant(writer, writer.id, "case_admin")).toThrow("permission");
    expect(() => f.context.access.revoke(reader, writer.id, "case_write")).toThrow("permission");
    expect(f.context.grantRepository.has(writer, "case_admin")).toBe(false);
  });

  test("the independent peer permission operation rejects the future cell value", () => {
    using f = fixture();
    expect(f.context.access.grantPeer(admin, "new-user", "case_read").permission).toBe("case_read");
    expect(() => f.context.access.grantPeer(admin, "new-user", "case_inspect")).toThrow("unsupported peer");
    expect(f.context.access.list(admin, "new-user")).toHaveLength(1);
  });

  test("both grant routes reject the future value and accept the base value", async () => {
    using f = fixture();
    for (const path of ["/grants", "/grants/peer"]) {
      const target = path.endsWith("peer") ? "peer-user" : "primary-user";
      const valid = await f.request("POST", path, {
        principal: target, project: "project", permission: "case_read",
      });
      expect(valid.status).toBe(201);
      expect(await valid.json()).toMatchObject({ principal: target, permission: "case_read" });
      await expectError(await f.request("POST", path, {
        principal: target, project: "project", permission: "case_inspect",
      }), 400);
    }
  });

  test("grant route cannot spoof a project", async () => {
    using f = fixture();
    await expectError(await f.request("POST", "/grants", {
      principal: "new-user", project: "other", permission: "case_admin",
    }), 403);
    expect(f.context.grantRepository.has({ id: "new-user", project: "other" }, "case_admin")).toBe(false);
  });

  test("invalid principal ids cannot become grant keys", () => {
    using f = fixture();
    expect(() => f.context.access.grant(admin, "bad/id", "case_read")).toThrow();
    expect(() => f.context.access.list(admin, "")).toThrow();
    expect(() => f.context.access.revoke(admin, "bad/id", "case_read")).toThrow();
    expect(f.context.grantRepository.has({ id: "bad/id", project: "project" }, "case_read")).toBe(false);
  });
});

describe("permission preferences and compound grants", () => {
  test("selected default permission is read from its sole owner", () => {
    using f = fixture();
    expect(f.context.access.getDefaultPermission(admin)).toBeNull();
    expect(() => f.context.access.grantDefault(admin, "new-user")).toThrow("no default");
    f.context.access.setDefaultPermission(admin, "case_read");
    expect(f.context.access.getDefaultPermission(admin)).toBe("case_read");
    expect(f.context.access.grantDefault(admin, "new-user").permission).toBe("case_read");
    f.context.access.setDefaultPermission(admin, "case_write");
    expect(f.context.access.grantDefault(admin, "another-user").permission).toBe("case_write");
    f.context.access.clearDefaultPermission(admin);
    expect(f.context.access.getDefaultPermission(admin)).toBeNull();
    expect(f.context.grantRepository.has({ id: "new-user", project: "project" }, "case_read")).toBe(true);
  });

  test("permission preferences are principal-scoped and do not grant privileges", () => {
    using f = fixture();
    f.context.access.setDefaultPermission(admin, "case_read");
    expect(f.context.access.getDefaultPermission(outsider)).toBeNull();
    f.context.access.setDefaultPermission(outsider, "case_admin");
    expect(f.context.access.getDefaultPermission(admin)).toBe("case_read");
    expect(() => f.context.access.setDefaultPermission(reader, "case_admin")).toThrow("permission");
    expect(() => f.context.access.setDefaultPermission(admin, "case_inspect")).toThrow();
    expect(f.context.access.getDefaultPermission(admin)).toBe("case_read");
  });

  test("bulk grants preserve individual provenance and idempotency", () => {
    using f = fixture();
    const grants = f.context.access.bulkGrant(admin, [
      { principal: "new-user", permission: "case_read" },
      { principal: "new-user", permission: "case_write" },
      { principal: "other-user", permission: "case_read" },
    ]);
    expect(grants).toHaveLength(3);
    expect(grants.every(grant => grant.grantedBy === admin.id)).toBe(true);
    expect(f.context.access.list(admin, "new-user")).toHaveLength(2);
    f.context.access.bulkGrant(admin, [{ principal: "new-user", permission: "case_read" }]);
    expect(f.context.access.list(admin, "new-user")).toHaveLength(2);
  });

  test("bulk revocation cannot remove the last administrator after earlier changes", () => {
    using f = fixture();
    expect(() => f.context.access.bulkRevoke(admin, [
      { principal: reader.id, permission: "case_read" },
      { principal: admin.id, permission: "case_admin" },
    ])).toThrow("last project administrator");
    expect(f.context.grantRepository.has(reader, "case_read")).toBe(true);
    expect(f.context.grantRepository.has(admin, "case_admin")).toBe(true);
  });

  test("bulk revocation returns per-item outcomes without inferring read access", () => {
    using f = fixture();
    const results = f.context.access.bulkRevoke(admin, [
      { principal: reader.id, permission: "case_read" },
      { principal: "missing", permission: "case_write" },
    ]);
    expect(results).toEqual([
      { principal: reader.id, permission: "case_read", revoked: true },
      { principal: "missing", permission: "case_write", revoked: false },
    ]);
    expect(() => f.context.access.require(reader, "case_read")).toThrow("permission");
  });

  test("HTTP defaults remain a selection rather than a hidden grant", async () => {
    using f = fixture();
    const selected = await f.request("PUT", "/preferences/permission", { permission: "case_read" });
    expect(selected.status).toBe(204);
    const current = await f.request("GET", "/preferences/permission");
    expect(await current.json()).toEqual({ permission: "case_read" });
    const granted = await f.request("POST", "/grants/default/new-user");
    expect(granted.status).toBe(201);
    expect(await granted.json()).toMatchObject({ principal: "new-user", permission: "case_read" });
    const cleared = await f.request("DELETE", "/preferences/permission");
    expect(cleared.status).toBe(204);
    const absent = await f.request("GET", "/preferences/permission");
    expect(await absent.json()).toEqual({ permission: null });
  });
});

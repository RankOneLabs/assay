import { describe, expect, test } from "bun:test";
import { peerGuard as stagePrimary, operations as stageOperations } from "../../stage/edit.ts";
import { peerGuard as evidencePrimary, operations as evidenceOperations } from "../../evidence_kind/edit.ts";
import { peerGuard as permissionPrimary, operations as permissionOperations } from "../../route_permission/edit.ts";
import { routeStage } from "../../src/routing.ts";
import { acceptValue as acceptStage } from "../../stage/policy.ts";
import { acceptValue as acceptKind } from "../../evidence_kind/policy.ts";
import { acceptValue as acceptPermission } from "../../route_permission/policy.ts";
import {
  acceptsPeerStage as stagePeer, acceptsPeerKind as evidencePeer, acceptsPeerPermission as permissionPeer,
} from "../../src/services/peer.ts";
import {
  DEFAULT_ROUTE, routeFor as registryRoute, validateRegisteredStage as validateStage,
  validateRegisteredKind as validateKind, validateRegisteredPermission as validatePermission,
} from "../../src/validation/registry.ts";
import { stageLabel, evidenceKindLabel, routePermissionLabel } from "../../src/presentation/labels.ts";
import { mediaFor, permissionDescription, canTransition } from "../../src/domain/transitions.ts";
import { fixture, admin } from "./helpers.ts";

const routeFor = (value: string) => registryRoute("stage", value);
const routeKind = (value: string) => registryRoute("evidence_kind", value);
const routePermission = (value: string) => registryRoute("route_permission", value);

/** Values that every version of the service keeps under the same spelling. */
const stableStages = ["active", "complete"] as const;
const stableKinds = ["image", "testimony"] as const;
const stablePermissions = ["case_write", "case_admin"] as const;

describe("feature-specific independent peer switch points", () => {
  test("stage primary and peer accept the stable stages", () => {
    for (const value of stableStages) {
      expect(stagePrimary(value)).toBe(true);
      expect(stagePeer(value)).toBe(true);
      expect(stageOperations[value]!("key")).toBe(`key:${value}`);
      expect(routeStage(value)).toStartWith("/jobs");
      expect(stageLabel(value)).toBe(value.charAt(0).toUpperCase() + value.slice(1));
    }
  });

  test("both stage peers reject unsupported and malformed stages", () => {
    expect(stagePrimary("unsupported_future")).toBe(false);
    expect(stagePeer("unsupported_future")).toBe(false);
    expect(stagePrimary("ACTIVE")).toBe(false);
    expect(stagePeer("ACTIVE")).toBe(false);
    expect(stagePrimary("active ")).toBe(false);
    expect(stagePeer("")).toBe(false);
  });

  test("evidence peers use evidence-kind values rather than stage values", () => {
    for (const value of stableKinds) {
      expect(evidencePrimary(value)).toBe(true);
      expect(evidencePeer(value)).toBe(true);
      expect(evidenceOperations[value]!("key")).toBe(`key:${value}`);
      expect(mediaFor(value)).toContain("/");
      expect(evidenceKindLabel(value)).toBe(value.charAt(0).toUpperCase() + value.slice(1));
    }
    expect(evidencePrimary("active")).toBe(false);
    expect(evidencePeer("active")).toBe(false);
    expect(evidencePrimary("unsupported_future")).toBe(false);
    expect(evidencePeer("unsupported_future")).toBe(false);
  });

  test("permission peers accept only permission vocabulary members", () => {
    for (const value of stablePermissions) {
      expect(permissionPrimary(value)).toBe(true);
      expect(permissionPeer(value)).toBe(true);
      expect(permissionOperations[value]!("key")).toBe(`key:${value}`);
      expect(permissionDescription(value).length).toBeGreaterThan(10);
      expect(routePermissionLabel(value)).toStartWith("Case ");
    }
    expect(permissionPrimary("image")).toBe(false);
    expect(permissionPeer("image")).toBe(false);
    expect(permissionPrimary("unsupported_future")).toBe(false);
    expect(permissionPeer("unsupported_future")).toBe(false);
  });

  test("reference policies accept stable values and reject unsupported ones", () => {
    expect(acceptStage("active")).toBe("active");
    expect(acceptKind("image")).toBe("image");
    expect(acceptPermission("case_write")).toBe("case_write");
    expect(() => acceptStage("unsupported_future")).toThrow("unsupported stage");
    expect(() => acceptKind("unsupported_future")).toThrow("unsupported evidence_kind");
    expect(() => acceptPermission("unsupported_future")).toThrow("unsupported route_permission");
  });

  test("descriptive registry validation is separate from edit operations", () => {
    expect(routeFor("active")).toBe("/jobs/active");
    expect(routeFor("unsupported_future")).toBe(DEFAULT_ROUTE);
    expect(validateStage("complete")).toBe(true);
    expect(validateStage("unsupported_future")).toBe(false);
    expect(routeKind("image")).toBe("/jobs/image");
    expect(validateKind("testimony")).toBe(true);
    expect(validateKind("unsupported_future")).toBe(false);
    expect(routePermission("case_admin")).toBe("/jobs/case_admin");
    expect(validatePermission("case_write")).toBe(true);
    expect(validatePermission("unsupported_future")).toBe(false);
  });

  test("stage transition rules are exhaustive without making complete reversible", () => {
    expect(canTransition("active", "complete")).toBe(true);
    expect(canTransition("complete", "active")).toBe(false);
    for (const stage of stableStages) expect(canTransition(stage, stage)).toBe(false);
  });

  test("HTTP stage peers both preserve baseline and reject future stages", async () => {
    using f = fixture();
    for (const peer of [false, true]) {
      const id = peer ? "peer-job" : "primary-job";
      const created = f.create(id);
      const path = `/jobs/${id}/stage${peer ? "/peer" : ""}`;
      const rejected = await f.request("POST", path, {
        stage: "unsupported_future", expectedRevision: 1, reason: "future stage",
      });
      expect(rejected.status).toBe(400);
      expect(f.context.jobRepository.require(id).stage).toBe(created.stage);
      const accepted = await f.request("POST", path, {
        stage: "active", expectedRevision: 1, reason: "start",
      });
      expect(accepted.status).toBe(200);
      expect(f.context.jobs.get(admin, id).stage).toBe("active");
    }
  });
});

describe("type-enforced feature types", () => {
  for (const [feature, typeName] of [["stage", "Stage"], ["evidence_kind", "EvidenceKind"], ["route_permission", "RoutePermission"]]) {
    test(`${feature} type is a closed union of its declared values`, async () => {
      const directory = `/tmp/type-control-${crypto.randomUUID()}`;
      const original = await Bun.file(`${import.meta.dir}/../../${feature}/types.ts`).text();
      try {
        await Bun.write(`${directory}/${feature}/types.ts`, original);
        await Bun.write(`${directory}/consumer.ts`, `import type { ${typeName} } from "./${feature}/types.ts"; const future: ${typeName} = "future_value"; void future;`);
        await Bun.write(`${directory}/tsconfig.json`, JSON.stringify({ compilerOptions: { target: "ESNext", module: "ESNext", moduleResolution: "bundler", strict: true, types: [], skipLibCheck: true, noEmit: true, allowImportingTsExtensions: true }, include: ["**/*.ts"] }));
        const command = [process.execPath, Bun.resolveSync("typescript/bin/tsc", import.meta.dir), "--noEmit", "-p", `${directory}/tsconfig.json`];
        const checked = Bun.spawnSync(command);
        expect(checked.exitCode).not.toBe(0);
        expect(new TextDecoder().decode(checked.stdout)).toContain("future_value");
        await Bun.write(`${directory}/${feature}/types.ts`, original.replace("] as const", ', "future_value"] as const'));
        expect(Bun.spawnSync(command).exitCode).toBe(0);
      } finally { await import("node:fs/promises").then(fs => fs.rm(directory, { recursive: true, force: true })); }
    }, 20000);
  }
});

for (const lookup of [routeFor, routeKind, routePermission]) {
  test("inherited object names use the default route", () => {
    for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      expect(lookup(name)).toBe(DEFAULT_ROUTE);
    }
  });
}

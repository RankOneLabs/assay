import { vocabularyStore as canonicalStore } from "../../src/vocabulary.ts";
function canonical(feature: string): never { return canonicalStore.values(feature)[0] as never; }
import { describe, expect, test } from "bun:test";
import { values as stages } from "../../stage/types.ts";
import { values as kinds } from "../../evidence_kind/types.ts";
import { values as permissions } from "../../route_permission/types.ts";
import { peerGuard as stagePrimary, operations as stageOperations } from "../../stage/edit.ts";
import { peerGuard as stagePeer } from "../../stage/sibling.ts";
import { peerGuard as evidencePrimary, operations as evidenceOperations } from "../../evidence_kind/edit.ts";
import { peerGuard as evidencePeer } from "../../evidence_kind/sibling.ts";
import { peerGuard as permissionPrimary, operations as permissionOperations } from "../../route_permission/edit.ts";
import { peerGuard as permissionPeer } from "../../route_permission/sibling.ts";
import { routeStage } from "../../src/routing.ts";
import { routeFor, DEFAULT_ROUTE } from "../../stage/names.ts";
import { routeFor as routeKind, validateRegisteredValue as validateKind } from "../../evidence_kind/names.ts";
import { routeFor as routePermission, validateRegisteredValue as validatePermission } from "../../route_permission/names.ts";
import { acceptValue as acceptStage } from "../../stage/policy.ts";
import { acceptValue as acceptKind } from "../../evidence_kind/policy.ts";
import { acceptValue as acceptPermission } from "../../route_permission/policy.ts";
import { mediaFor, permissionDescription, canTransition } from "../../src/domain/transitions.ts";
import { fixture, admin } from "./helpers.ts";

describe("feature-specific independent peer switch points", () => {
  test("stage primary and peer accept the baseline vocabulary", () => {
    for (const value of stages) {
      expect(stagePrimary(value)).toBe(true);
      expect(stagePeer(value)).toBe(true);
      expect(stageOperations[value]("key")).toBe(`key:${value}`);
      expect(routeStage(value)).toStartWith("/jobs");
    }
  });

  test("both stage peers reject the additive and renamed cell target", () => {
    expect(stagePrimary("unsupported_future")).toBe(false);
    expect(stagePeer("unsupported_future")).toBe(false);
    expect(stagePrimary("QUEUED")).toBe(false);
    expect(stagePeer("QUEUED")).toBe(false);
    expect(stagePrimary("queued ")).toBe(false);
    expect(stagePeer("")).toBe(false);
  });

  test("evidence peers use evidence-kind values rather than stage values", () => {
    for (const value of kinds) {
      expect(evidencePrimary(value)).toBe(true);
      expect(evidencePeer(value)).toBe(true);
      expect(evidenceOperations[value]("key")).toBe(`key:${value}`);
      expect(mediaFor(value)).toContain("/");
    }
    expect(evidencePrimary(canonical("stage"))).toBe(false);
    expect(evidencePeer(canonical("stage"))).toBe(false);
    expect(evidencePrimary("unsupported_future")).toBe(false);
    expect(evidencePeer("unsupported_future")).toBe(false);
  });

  test("permission peers accept only permission vocabulary members", () => {
    for (const value of permissions) {
      expect(permissionPrimary(value)).toBe(true);
      expect(permissionPeer(value)).toBe(true);
      expect(permissionOperations[value]("key")).toBe(`key:${value}`);
      expect(permissionDescription(value).length).toBeGreaterThan(10);
    }
    expect(permissionPrimary(canonical("evidence_kind"))).toBe(false);
    expect(permissionPeer(canonical("evidence_kind"))).toBe(false);
    expect(permissionPrimary("unsupported_future")).toBe(false);
    expect(permissionPeer("unsupported_future")).toBe(false);
  });

  test("reference policies reject each feature's new cell value", () => {
    expect(acceptStage(canonical("stage"))).toBe(canonical("stage"));
    expect(acceptKind(canonical("evidence_kind"))).toBe(canonical("evidence_kind"));
    expect(acceptPermission(canonical("route_permission"))).toBe(canonical("route_permission"));
    expect(() => acceptStage("unsupported_future")).toThrow("unsupported stage");
    expect(() => acceptKind("unsupported_future")).toThrow("unsupported evidence_kind");
    expect(() => acceptPermission("unsupported_future")).toThrow("unsupported route_permission");
  });

  test("descriptive registry validation is separate from edit operations", () => {
    expect(routeFor(canonical("stage"))).toBe((`/jobs/${canonical("stage")}`));
    expect(routeFor("unsupported_future")).toBe(DEFAULT_ROUTE);
    expect(validateKind(canonical("evidence_kind"))).toBe(true);
    expect(validateKind("unsupported_future")).toBe(false);
    expect(validatePermission(canonical("route_permission"))).toBe(true);
    expect(validatePermission("unsupported_future")).toBe(false);
  });

  test("stage transition rules are exhaustive without making complete reversible", () => {
    expect(canTransition(canonical("stage"), "active")).toBe(true);
    expect(canTransition(canonical("stage"), "complete")).toBe(false);
    expect(canTransition("active", canonical("stage"))).toBe(true);
    expect(canTransition("active", "complete")).toBe(true);
    expect(canTransition("complete", canonical("stage"))).toBe(false);
    expect(canTransition("complete", "active")).toBe(false);
    for (const stage of stages) expect(canTransition(stage, stage)).toBe(false);
  });

  test("HTTP stage peers both preserve baseline and reject future stages", async () => {
    using f = fixture();
    for (const peer of [false, true]) {
      const id = peer ? "peer-job" : "primary-job";
      f.create(id);
      const path = `/jobs/${id}/stage${peer ? "/peer" : ""}`;
      const rejected = await f.request("POST", path, {
        stage: "unsupported_future", expectedRevision: 1, reason: "future stage",
      });
      expect(rejected.status).toBe(400);
      expect(f.context.jobRepository.require(id).stage).toBe(canonical("stage"));
      const accepted = await f.request("POST", path, {
        stage: "active", expectedRevision: 1, reason: "start",
      });
      expect(accepted.status).toBe(200);
      expect(f.context.jobs.get(admin, id).stage).toBe("active");
    }
  });
});

/** Only a literal owner in types.ts provides a closed compile-time vocabulary. */
describe("type-enforced owner controls", () => {
  for (const [feature, typeName] of [["stage", "Stage"], ["evidence_kind", "EvidenceKind"], ["route_permission", "RoutePermission"]]) {
    test(`${feature} type is closed exactly when types.ts owns the vocabulary`, async () => {
      const directory = `/tmp/type-control-${crypto.randomUUID()}`;
      const original = await Bun.file(`${import.meta.dir}/../../${feature}/types.ts`).text();
      const closed = original.includes("vocabularyStore.define");
      try {
        await Bun.write(`${directory}/${feature}/types.ts`, original);
        await Bun.write(`${directory}/src/vocabulary.ts`, await Bun.file(`${import.meta.dir}/../../src/vocabulary.ts`).text());
        await Bun.write(`${directory}/consumer.ts`, `import type { ${typeName} } from "./${feature}/types.ts"; const future: ${typeName} = "future_value"; void future;`);
        await Bun.write(`${directory}/tsconfig.json`, JSON.stringify({ compilerOptions: { target: "ESNext", module: "ESNext", moduleResolution: "bundler", strict: true, types: [], skipLibCheck: true, noEmit: true, allowImportingTsExtensions: true }, include: ["**/*.ts"] }));
        const command = [process.execPath, Bun.resolveSync("typescript/bin/tsc", import.meta.dir), "--noEmit", "-p", `${directory}/tsconfig.json`];
        const checked = Bun.spawnSync(command);
        expect(checked.exitCode === 0).toBe(!closed);
        if (closed) {
          expect(new TextDecoder().decode(checked.stdout)).toContain("future_value");
          await Bun.write(`${directory}/${feature}/types.ts`, original.replace("] as const", ', "future_value"] as const'));
          expect(Bun.spawnSync(command).exitCode).toBe(0);
        }
      } finally { await import("node:fs/promises").then(fs => fs.rm(directory, { recursive: true, force: true })); }
    }, 20000);
  }
});

for (const [feature, primary] of [["stage", stagePrimary], ["evidence_kind", evidencePrimary], ["route_permission", permissionPrimary]] as const) {
  test(`${feature} sibling derives the current owner vocabulary`, async () => {
    const peer = await import(`../../${feature}/sibling.ts`) as { peerGuard(value: string): boolean };
    const types = await import(`../../${feature}/types.ts`) as { values: readonly string[] };
    for (const value of types.values) expect(peer.peerGuard(value)).toBe(primary(value));
    expect(peer.peerGuard("future_value")).toBe(false);
  });
}

for (const lookup of [routeFor, routeKind, routePermission]) {
  test("inherited object names use the default route", () => {
    for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      expect(lookup(name)).toBe(DEFAULT_ROUTE);
    }
  });
}

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
      expect(routeStage(value)).toStartWith("/jobs/");
    }
  });

  test("both stage peers reject the additive and renamed cell target", () => {
    expect(stagePrimary("triaged")).toBe(false);
    expect(stagePeer("triaged")).toBe(false);
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
    expect(evidencePrimary("queued")).toBe(false);
    expect(evidencePeer("queued")).toBe(false);
    expect(evidencePrimary("attestation")).toBe(false);
    expect(evidencePeer("attestation")).toBe(false);
  });

  test("permission peers accept only permission vocabulary members", () => {
    for (const value of permissions) {
      expect(permissionPrimary(value)).toBe(true);
      expect(permissionPeer(value)).toBe(true);
      expect(permissionOperations[value]("key")).toBe(`key:${value}`);
      expect(permissionDescription(value).length).toBeGreaterThan(10);
    }
    expect(permissionPrimary("document")).toBe(false);
    expect(permissionPeer("document")).toBe(false);
    expect(permissionPrimary("case_inspect")).toBe(false);
    expect(permissionPeer("case_inspect")).toBe(false);
  });

  test("reference policies reject each feature's new cell value", () => {
    expect(acceptStage("queued")).toBe("queued");
    expect(acceptKind("document")).toBe("document");
    expect(acceptPermission("case_read")).toBe("case_read");
    expect(() => acceptStage("triaged")).toThrow("unsupported stage");
    expect(() => acceptKind("attestation")).toThrow("unsupported evidence_kind");
    expect(() => acceptPermission("case_inspect")).toThrow("unsupported route_permission");
  });

  test("descriptive registry validation is separate from edit operations", () => {
    expect(routeFor("queued")).toBe("/jobs/queued");
    expect(routeFor("triaged")).toBe(DEFAULT_ROUTE);
    expect(validateKind("document")).toBe(true);
    expect(validateKind("attestation")).toBe(false);
    expect(validatePermission("case_read")).toBe(true);
    expect(validatePermission("case_inspect")).toBe(false);
  });

  test("stage transition rules are exhaustive without making complete reversible", () => {
    expect(canTransition("queued", "active")).toBe(true);
    expect(canTransition("queued", "complete")).toBe(false);
    expect(canTransition("active", "queued")).toBe(true);
    expect(canTransition("active", "complete")).toBe(true);
    expect(canTransition("complete", "queued")).toBe(false);
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
        stage: "triaged", expectedRevision: 1, reason: "future stage",
      });
      expect(rejected.status).toBe(400);
      expect(f.context.jobRepository.require(id).stage).toBe("queued");
      const accepted = await f.request("POST", path, {
        stage: "active", expectedRevision: 1, reason: "start",
      });
      expect(accepted.status).toBe(200);
      expect(f.context.jobs.get(admin, id).stage).toBe("active");
    }
  });
});

/** Prove that each feature's control actually fails compilation when extended alone. */
describe("type-enforced mutation controls", () => {
  for (const feature of ["stage", "evidence_kind", "route_permission"]) {
    test(`${feature} requires the exhaustive operation record to be extended`, async () => {
      const directory = `/tmp/type-control-${crypto.randomUUID()}`;
      const files = ["types.ts", "edit.ts", "policy.ts", "anchor.ts", "tsconfig.json"];
      const original = await Bun.file(`${import.meta.dir}/../../${feature}/types.ts`).text();
      const environment = { ...process.env };
      delete environment.BUN_INSPECT;
      try {
        for (const file of files.slice(0, -1)) {
          const source = await Bun.file(`${import.meta.dir}/../../${feature}/${file}`).text();
          await Bun.write(`${directory}/${file}`, source);
        }
        await Bun.write(`${directory}/tsconfig.json`, JSON.stringify({
          compilerOptions: {
            target: "ESNext",
            module: "ESNext",
            moduleResolution: "bundler",
            strict: true,
            types: [],
            skipLibCheck: true,
            noEmit: true,
            allowImportingTsExtensions: true,
          },
          include: ["*.ts"],
        }));
        const command = [
          process.execPath,
          Bun.resolveSync("typescript/bin/tsc", import.meta.dir),
          "--noEmit", "-p", `${directory}/tsconfig.json`,
        ];
        const clean = Bun.spawnSync(command, { env: environment });
        expect(new TextDecoder().decode(clean.stdout)).toBe("");
        expect(clean.exitCode).toBe(0);
        expect(original).toContain("] as const");
        await Bun.write(`${directory}/types.ts`, original.replace("] as const", ', "future_value"] as const'));
        const changed = Bun.spawnSync(command, { env: environment });
        expect(changed.exitCode).not.toBe(0);
        const diagnostics = new TextDecoder().decode(changed.stdout);
        expect(diagnostics).toContain("future_value");
        expect(diagnostics).toContain("missing");
        expect(diagnostics).toContain("edit.ts");
      } finally {
        for (const file of files) {
          const path = Bun.file(`${directory}/${file}`);
          if (await path.exists()) await path.delete();
        }
      }
    }, 20000);
  }
});

describe("independent sibling acceptance mutations", () => {
  for (const [feature, future, primary] of [
    ["stage", "triaged", stagePrimary],
    ["evidence_kind", "attestation", evidencePrimary],
    ["route_permission", "case_inspect", permissionPrimary],
  ] as const) {
    test(`${feature}: changing only the sibling changes only its acceptance`, async () => {
      const path = `/tmp/sibling-control-${crypto.randomUUID()}.ts`;
      const original = await Bun.file(`${import.meta.dir}/../../${feature}/sibling.ts`).text();
      expect(primary(future)).toBe(false);
      expect(original).toContain("switch (value)");
      const extended = original.replace("switch (value) {", `switch (value) {\n    case "${future}":`);
      try {
        await Bun.write(path, extended);
        const changed = await import(path) as { peerGuard: (value: string) => boolean };
        expect(changed.peerGuard(future)).toBe(true);
        expect(primary(future)).toBe(false);
        expect(changed.peerGuard("invalid-value")).toBe(false);
        expect(await Bun.file(`${import.meta.dir}/../../${feature}/sibling.ts`).text()).toBe(original);
      } finally {
        if (await Bun.file(path).exists()) await Bun.file(path).delete();
      }
    });
  }
});

for (const lookup of [routeFor, routeKind, routePermission]) {
  test("inherited object names use the default route", () => {
    for (const name of ["constructor", "toString", "__proto__", "hasOwnProperty"]) {
      expect(lookup(name)).toBe(DEFAULT_ROUTE);
    }
  });
}

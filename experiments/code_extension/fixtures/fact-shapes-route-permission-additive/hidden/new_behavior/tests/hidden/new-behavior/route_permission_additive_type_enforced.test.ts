import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { rmSync } from "node:fs";
import { routePermissionLabels } from "../../../src/presentation/route_permission_labels.ts";

test("fact:route_permission_additive_type_enforced: type_enforced behavior", async () => {
  const directory = `/tmp/fact-public-type-${crypto.randomUUID()}`;
  try {
    const config = JSON.parse(await Bun.file("tsconfig.json").text());
    config.compilerOptions.types = [Bun.resolveSync("@types/bun/index.d.ts", import.meta.dir)];
    config.include = ["consumer.ts"];
    await Bun.write(`${directory}/tsconfig.json`, JSON.stringify(config));
    await Bun.write(`${directory}/consumer.ts`, [
      `import { edit } from ${JSON.stringify(process.cwd() + "/route_permission/edit.ts")};`,
      `import { routePermissionLabels } from ${JSON.stringify(process.cwd() + "/src/presentation/route_permission_labels.ts")};`,
      `edit("record", "case_inspect");`,
      `export const displayed: string = routePermissionLabels.case_inspect;`,
    ].join("\n"));
    const result = Bun.spawnSync([process.execPath, Bun.resolveSync("typescript/bin/tsc", import.meta.dir), "--noEmit", "-p", `${directory}/tsconfig.json`]);
    expect(new TextDecoder().decode(result.stdout) + new TextDecoder().decode(result.stderr)).toBe("");
    expect(result.exitCode).toBe(0);
  } finally { rmSync(directory, { recursive: true, force: true }); }
  expect(typeof (routePermissionLabels as Record<string, unknown>)["case_inspect"]).toBe("string");
}, 30000);

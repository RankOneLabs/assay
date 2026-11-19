import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { rmSync } from "node:fs";
import { stageLabels } from "../../../src/presentation/labels.ts";

test("fact:stage_additive_type_enforced: type_enforced behavior", async () => {
  const directory = `/tmp/fact-public-type-${crypto.randomUUID()}`;
  try {
    const config = JSON.parse(await Bun.file("tsconfig.json").text());
    config.compilerOptions.types = [Bun.resolveSync("@types/bun/index.d.ts", import.meta.dir)];
    config.include = ["consumer.ts"];
    await Bun.write(`${directory}/tsconfig.json`, JSON.stringify(config));
    await Bun.write(`${directory}/consumer.ts`, [
      `import { edit } from ${JSON.stringify(process.cwd() + "/stage/edit.ts")};`,
      `import { stageLabels } from ${JSON.stringify(process.cwd() + "/src/presentation/labels.ts")};`,
      `edit("record", "triaged");`,
      `export const displayed: string = stageLabels.triaged;`,
    ].join("\n"));
    const result = Bun.spawnSync([process.execPath, Bun.resolveSync("typescript/bin/tsc", import.meta.dir), "--noEmit", "-p", `${directory}/tsconfig.json`]);
    expect(new TextDecoder().decode(result.stdout) + new TextDecoder().decode(result.stderr)).toBe("");
    expect(result.exitCode).toBe(0);
  } finally { rmSync(directory, { recursive: true, force: true }); }
  expect(typeof (stageLabels as Record<string, unknown>)["triaged"]).toBe("string");
}, 30000);

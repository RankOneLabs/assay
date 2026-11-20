import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { rmSync } from "node:fs";
import { ServiceContext } from "../../../src/context.ts";

test("fact:stage_additive_type_enforced: type_enforced behavior", async () => {
  const directory = `/tmp/fact-public-type-${crypto.randomUUID()}`;
  try {
    const config = JSON.parse(await Bun.file("tsconfig.json").text());
    config.compilerOptions.types = [Bun.resolveSync("@types/bun/index.d.ts", import.meta.dir)];
    config.include = ["consumer.ts"];
    await Bun.write(`${directory}/tsconfig.json`, JSON.stringify(config));
    await Bun.write(`${directory}/consumer.ts`, [
      `import { stageHeadings } from ${JSON.stringify(process.cwd() + "/src/presentation/labels.ts")};`,
      `export const shown: string = stageHeadings.triaged;`,
    ].join("\n"));
    const result = Bun.spawnSync([process.execPath, Bun.resolveSync("typescript/bin/tsc", import.meta.dir), "--noEmit", "-p", `${directory}/tsconfig.json`]);
    expect(new TextDecoder().decode(result.stdout) + new TextDecoder().decode(result.stderr)).toBe("");
    expect(result.exitCode).toBe(0);
  } finally { rmSync(directory, { recursive: true, force: true }); }
  using context = new ServiceContext();
  const actor = { id: "admin", project: "project" };
  for (const permission of ["case_read", "case_write", "case_admin"]) context.grantRepository.grant(actor, permission as never, "bootstrap", 0);
  const row = context.reports.summary(actor).stages.find(item => item.stage === ("triaged" as never));
  expect(row?.label).toBe("Awaiting triage");
}, 30000);

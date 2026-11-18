import { expect, test } from "bun:test";
import "../../../src/bootstrap.ts";
import { rmSync } from "node:fs";
import { evidenceKindLabels } from "../../../src/presentation/evidence_kind_labels.ts";
import { edit } from "../../../evidence_kind/edit.ts";

test("fact:evidence_kind_rename_type_enforced: type_enforced behavior", async () => {
  const directory = `/tmp/fact-public-type-${crypto.randomUUID()}`;
  try {
    const config = JSON.parse(await Bun.file("tsconfig.json").text());
    config.compilerOptions.types = [Bun.resolveSync("@types/bun/index.d.ts", import.meta.dir)];
    config.include = ["consumer.ts"];
    await Bun.write(`${directory}/tsconfig.json`, JSON.stringify(config));
    await Bun.write(`${directory}/consumer.ts`, [
      `import { edit } from ${JSON.stringify(process.cwd() + "/evidence_kind/edit.ts")};`,
      `import { evidenceKindLabels } from ${JSON.stringify(process.cwd() + "/src/presentation/evidence_kind_labels.ts")};`,
      `edit("record", "attestation");`,
      `export const displayed: string = evidenceKindLabels.attestation;`,
    ].join("\n"));
    const result = Bun.spawnSync([process.execPath, Bun.resolveSync("typescript/bin/tsc", import.meta.dir), "--noEmit", "-p", `${directory}/tsconfig.json`]);
    expect(new TextDecoder().decode(result.stdout) + new TextDecoder().decode(result.stderr)).toBe("");
    expect(result.exitCode).toBe(0);
  } finally { rmSync(directory, { recursive: true, force: true }); }
  expect(typeof (evidenceKindLabels as Record<string, unknown>)["attestation"]).toBe("string");
  expect(() => edit("record", "document" as never)).toThrow();
}, 30000);

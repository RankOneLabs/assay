import { cp, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";

const webRoot = resolve(import.meta.dir, "..");
const output = resolve(webRoot, "../src/assay/review/static");

await mkdir(output, { recursive: true });
const result = await Bun.build({
  entrypoints: [resolve(webRoot, "src/app.ts")],
  outdir: output,
  naming: "app.js",
  target: "browser",
  format: "esm",
  minify: true,
  sourcemap: "none",
});
if (!result.success) {
  for (const log of result.logs) console.error(log);
  process.exit(1);
}
await Promise.all([
  cp(resolve(webRoot, "src/app.css"), resolve(output, "app.css")),
  cp(resolve(webRoot, "src/index.html"), resolve(output, "index.html")),
]);

for (const asset of ["app.js", "app.css", "index.html"]) {
  const file = resolve(output, asset);
  if (dirname(file) !== output) throw new Error("asset escaped output directory");
}

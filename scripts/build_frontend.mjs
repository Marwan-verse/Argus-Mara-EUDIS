// Ship self-contained browser bundles: Python serving and exported packs need no Node runtime.
import { build } from "esbuild";
import { compile } from "svelte/compiler";
import { readFile, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
const sveltePlugin = {
  name: "svelte",
  setup(build) {
    build.onLoad({ filter: /\.svelte$/ }, async ({ path }) => {
      const result = compile(await readFile(path, "utf8"), {
        filename: path,
        generate: "client",
        css: "external",
      });
      for (const warning of result.warnings)
        console.warn(`${path}: ${warning.code}: ${warning.message}`);
      if (result.css?.code)
        throw new Error(
          "Use the existing global stylesheets for offline, self-contained exports.",
        );
      return { contents: result.js.code, loader: "js" };
    });
  },
};
for (const [entry, outfile, format] of [
  ["ui/src/replay.js", "ui/app.mjs", "esm"],
  ["ui/src/live.js", "ui/live/dashboard.mjs", "esm"],
  ["ui/src/evidence.js", "ui/space/evidence.js", "iife"],
  ["ui/src/recorder.js", "ui/recorder.js", "iife"],
]) {
  await build({
    entryPoints: [entry],
    outfile,
    bundle: true,
    minify: true,
    format,
    platform: "browser",
    supported: { "template-literal": false },
    conditions: ["browser", "production"],
    target: ["es2022"],
    plugins: [sveltePlugin],
    logLevel: "info",
  });
}

// Refresh only the compiled asset in the existing fictional pack. Preserve data/provenance.
const evidence = await readFile("ui/space/evidence.js");
await writeFile("ui/evidence/assets/evidence.js", evidence);
const manifest = JSON.parse(
  await readFile("ui/evidence/manifest.json", "utf8"),
);
const entry = manifest.files.find((file) => file.path === "assets/evidence.js");
if (!entry)
  throw new Error(
    "The fictional evidence manifest is missing its script entry.",
  );
entry.sha256 = createHash("sha256").update(evidence).digest("hex");
entry.bytes = evidence.length;
await writeFile(
  "ui/evidence/manifest.json",
  JSON.stringify(manifest, null, 2) + "\n",
);

// Official Svelte analysis; its initialization also retrieves the online docs index.
import { svelteAutofixer } from "@sveltejs/mcp";
import { readdir, readFile } from "node:fs/promises";
for (const filename of (await readdir("ui/src")).filter((name) =>
  name.endsWith(".svelte"),
)) {
  const result = await svelteAutofixer({
    code: await readFile(`ui/src/${filename}`, "utf8"),
    desired_svelte_version: 5,
    filename,
  });
  console.log(filename, JSON.stringify(result));
  if (result.issues.length) process.exitCode = 1;
}

import { readFile, writeFile } from "node:fs/promises";
import { stripTypeScriptTypes } from "node:module";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const files = [
  "types.ts", "core.ts", "shell.ts", "views_overview.ts", "views_analysis.ts",
  "views_matches.ts", "views_people.ts",
  "views_history.ts", "views_manual.ts", "views_media.ts", "bindings.ts", "app.ts",
];
const chunks = [];
for (const file of files) {
  const source = await readFile(resolve(root, "frontend", "src", file), "utf8");
  chunks.push(stripTypeScriptTypes(source, { mode: "transform", sourceMap: false }));
}
await writeFile(
  resolve(root, "atlas", "static", "app.js"),
  `/* Project Atlas Tracker v1.2.5 — generated from frontend/src */\n${chunks.join("\n")}\n`,
  "utf8",
);

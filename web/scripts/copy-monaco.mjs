// Copy the prebuilt Monaco editor into public/, so our own server serves it (runs after
// `npm install` / `npm ci`). Without this, @monaco-editor/react downloads Monaco at runtime
// from cdn.jsdelivr.net: third-party code without an integrity check, and no editor offline.
import { cpSync, existsSync, rmSync } from "node:fs";

const source = "node_modules/monaco-editor/min/vs";
const target = "public/monaco/vs";

if (!existsSync(`${source}/loader.js`)) {
  console.error(`copy-monaco: ${source}/loader.js not found (is monaco-editor installed?)`);
  process.exit(1);
}
rmSync("public/monaco", { recursive: true, force: true }); // no files left from an old version
cpSync(source, target, { recursive: true });
console.log(`copy-monaco: ${source} -> ${target}`);

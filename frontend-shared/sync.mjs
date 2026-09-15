// Sync this shared source tree into a consuming app as ./_shared (a gitignored
// build artifact). Run from the app dir before dev/build/typecheck:
//
//   node ../frontend-shared/sync.mjs ./_shared
//
// Why a copy instead of a path alias to ../frontend-shared: keeping the files
// INSIDE the app dir lets TypeScript, Tailwind's @source scan, and Next's
// standalone file-tracing all resolve them with zero monorepo/tsconfig hacks
// (react/@types resolve via the app's own node_modules). frontend-shared/ stays
// the single source of truth — _shared is regenerated, never edited, never
// committed.
import { cpSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const src = dirname(fileURLToPath(import.meta.url)); // the frontend-shared dir
const target = resolve(process.cwd(), process.argv[2] ?? "./_shared");

// Only the source tree travels; tooling/meta files stay out of the app bundle.
const EXCLUDE = new Set(["sync.mjs", "README.md", "package.json", "node_modules", ".git"]);

rmSync(target, { recursive: true, force: true });
cpSync(src, target, {
  recursive: true,
  filter: (from) => {
    if (from === src) return true;
    const top = from.slice(src.length + 1).split(/[\\/]/)[0];
    return !EXCLUDE.has(top);
  },
});
console.log(`[sync-shared] ${src} -> ${target}`);

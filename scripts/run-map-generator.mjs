import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolvePythonInterpreter } from "./lib/python-resolver.mjs";
import fs from "node:fs";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);
const rootDir = path.resolve(currentDir, "..");

// Resolve a working Python interpreter up front (each candidate is probed,
// so stale virtualenvs and uninstalled interpreters are skipped automatically).
const resolvedPython = resolvePythonInterpreter(rootDir);

const candidateCommands = [
  {
    command: resolvedPython.command,
    argsPrefix: resolvedPython.args,
  },
];

const userArgs = process.argv.slice(2);
let lastFailure = null;

for (const candidate of candidateCommands) {
  if (candidate.command.includes(path.sep) && !fs.existsSync(candidate.command)) {
    continue;
  }

  const result = spawnSync(
    candidate.command,
    [...candidate.argsPrefix, "-m", "tools.map_generator.cli", ...userArgs],
    {
      cwd: rootDir,
      stdio: "inherit",
      shell: false,
    },
  );

  if (typeof result.status === "number") {
    process.exit(result.status);
  }

  lastFailure = result.error;
}

console.error(
  "Could not find a usable Python interpreter. Create .venv or install Python 3.10+ with the Windows py launcher.",
);

if (lastFailure) {
  console.error(lastFailure.message);
}

process.exit(1);

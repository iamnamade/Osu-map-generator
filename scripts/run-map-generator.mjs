import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import fs from "node:fs";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);
const rootDir = path.resolve(currentDir, "..");

const candidateCommands = [
  {
    command: path.join(rootDir, ".venv", "Scripts", "python.exe"),
    argsPrefix: [],
  },
  {
    command: path.join(rootDir, ".venv", "bin", "python"),
    argsPrefix: [],
  },
  {
    command: "python",
    argsPrefix: [],
  },
  {
    command: "py",
    argsPrefix: ["-3"],
  },
  {
    command: "py",
    argsPrefix: [],
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

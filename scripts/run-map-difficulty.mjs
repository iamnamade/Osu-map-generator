import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

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

const presetCommands = {
  easy: [
    "difficulty",
    "--map",
    "public/maps/generated/test-song-easy.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--difficulty",
    "easy",
    "--output",
    "public/difficulty/test-song-easy-difficulty.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  normal: [
    "difficulty",
    "--map",
    "public/maps/generated/test-song-normal.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--difficulty",
    "normal",
    "--output",
    "public/difficulty/test-song-normal-difficulty.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  hard: [
    "difficulty",
    "--map",
    "public/maps/generated/test-song-hard.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--difficulty",
    "hard",
    "--output",
    "public/difficulty/test-song-hard-difficulty.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  all: [
    "difficulty",
    "--map",
    "public/maps/generated/test-song-easy.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--difficulty",
    "easy",
    "--output",
    "public/difficulty/test-song-easy-difficulty.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
};

const userArgs = process.argv.slice(2);
const normalizedArgs =
  userArgs.length === 0
    ? presetCommands.all
    : presetCommands[userArgs[0]] ?? userArgs;

let lastFailure = null;

for (const candidate of candidateCommands) {
  if (candidate.command.includes(path.sep) && !fs.existsSync(candidate.command)) {
    continue;
  }

  const result = spawnSync(
    candidate.command,
    [...candidate.argsPrefix, "-m", "tools.map_generator.cli", ...normalizedArgs],
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

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
    "improve",
    "--map",
    "public/maps/generated/test-song-easy.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--report",
    "public/reports/test-song-easy-report.json",
    "--difficulty",
    "easy",
    "--seed",
    "42",
    "--output",
    "public/maps/improved/test-song-easy-improved.json",
    "--report-output",
    "public/reports/improved/test-song-easy-improved-report.json",
    "--changes-output",
    "public/corrections/test-song-easy-corrections.json",
  ],
  normal: [
    "improve",
    "--map",
    "public/maps/generated/test-song-normal.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--report",
    "public/reports/test-song-normal-report.json",
    "--difficulty",
    "normal",
    "--seed",
    "42",
    "--output",
    "public/maps/improved/test-song-normal-improved.json",
    "--report-output",
    "public/reports/improved/test-song-normal-improved-report.json",
    "--changes-output",
    "public/corrections/test-song-normal-corrections.json",
  ],
  hard: [
    "improve",
    "--map",
    "public/maps/generated/test-song-hard.json",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--report",
    "public/reports/test-song-hard-report.json",
    "--difficulty",
    "hard",
    "--seed",
    "42",
    "--output",
    "public/maps/improved/test-song-hard-improved.json",
    "--report-output",
    "public/reports/improved/test-song-hard-improved-report.json",
    "--changes-output",
    "public/corrections/test-song-hard-corrections.json",
  ],
  all: [
    "improve-all",
    "--maps-dir",
    "public/maps/generated",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--reports-dir",
    "public/reports",
    "--output-dir",
    "public/maps/improved",
    "--improved-reports-dir",
    "public/reports/improved",
    "--corrections-dir",
    "public/corrections",
    "--seed",
    "42",
  ],
  compare: [
    "compare-improvements",
    "--original-reports-dir",
    "public/reports",
    "--improved-reports-dir",
    "public/reports/improved",
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

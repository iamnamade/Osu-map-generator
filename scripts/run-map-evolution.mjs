import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolvePythonInterpreter } from "./lib/python-resolver.mjs";

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

const presetCommands = {
  easy: [
    "evolution",
    "--audio",
    "public/audio/test-song.mp3",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--title",
    "Test Song",
    "--artist",
    "Unknown Artist",
    "--difficulty",
    "easy",
    "--seed",
    "42",
    "--output-root",
    "public/candidates/test-song/easy",
    "--champion-map",
    "public/maps/champions/test-song-easy.json",
    "--champion-report",
    "public/reports/champions/test-song-easy-report.json",
    "--evolution-report",
    "public/evolution/test-song-easy-evolution.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  normal: [
    "evolution",
    "--audio",
    "public/audio/test-song.mp3",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--title",
    "Test Song",
    "--artist",
    "Unknown Artist",
    "--difficulty",
    "normal",
    "--seed",
    "42",
    "--output-root",
    "public/candidates/test-song/normal",
    "--champion-map",
    "public/maps/champions/test-song-normal.json",
    "--champion-report",
    "public/reports/champions/test-song-normal-report.json",
    "--evolution-report",
    "public/evolution/test-song-normal-evolution.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  hard: [
    "evolution",
    "--audio",
    "public/audio/test-song.mp3",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--title",
    "Test Song",
    "--artist",
    "Unknown Artist",
    "--difficulty",
    "hard",
    "--seed",
    "42",
    "--output-root",
    "public/candidates/test-song/hard",
    "--champion-map",
    "public/maps/champions/test-song-hard.json",
    "--champion-report",
    "public/reports/champions/test-song-hard-report.json",
    "--evolution-report",
    "public/evolution/test-song-hard-evolution.json",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  all: [
    "evolution-all",
    "--audio",
    "public/audio/test-song.mp3",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--title",
    "Test Song",
    "--artist",
    "Unknown Artist",
    "--seed",
    "42",
    "--sections",
    "public/sections/test-song-sections.json",
  ],
  compare: [
    "compare-evolutions",
    "--evolutions-dir",
    "public/evolution",
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

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
    [
      "export-osu",
      "--map",
      "public/maps/hybrid/test-song-easy.json",
      "--analysis",
      "public/analysis/test-song-analysis.json",
      "--output",
      "public/exports/osu/test-song-easy.osu",
      "--creator",
      "osu-map-ai",
      "--version-name",
      "Hybrid Easy",
    ],
  ],
  normal: [
    [
      "export-osu",
      "--map",
      "public/maps/hybrid/test-song-normal.json",
      "--analysis",
      "public/analysis/test-song-analysis.json",
      "--output",
      "public/exports/osu/test-song-normal.osu",
      "--creator",
      "osu-map-ai",
      "--version-name",
      "Hybrid Normal",
    ],
  ],
  hard: [
    [
      "export-osu",
      "--map",
      "public/maps/hybrid/test-song-hard.json",
      "--analysis",
      "public/analysis/test-song-analysis.json",
      "--output",
      "public/exports/osu/test-song-hard.osu",
      "--creator",
      "osu-map-ai",
      "--version-name",
      "Hybrid Hard",
    ],
  ],
  all: [
    [
      "export-osu-mapset",
      "--maps-dir",
      "public/maps/hybrid",
      "--analysis",
      "public/analysis/test-song-analysis.json",
      "--audio",
      "public/audio/test-song.mp3",
      "--output-dir",
      "public/exports/osu/test-song",
    ],
  ],
  package: [
    [
      "package-osz",
      "--maps-dir",
      "public/exports/osu/test-song",
      "--audio",
      "public/audio/test-song.mp3",
      "--output",
      "public/exports/mapsets/test-song.osz",
    ],
  ],
  validate: [
    ["validate-osu", "--input", "public/exports/osu/test-song-easy.osu"],
    ["validate-osu", "--input", "public/exports/osu/test-song-normal.osu"],
    ["validate-osu", "--input", "public/exports/osu/test-song-hard.osu"],
  ],
};

const userArgs = process.argv.slice(2);
const [mode = "all", ...rest] = userArgs;
const commandSets = resolvePresetCommands(mode, rest);

let lastFailure = null;

for (const candidate of candidateCommands) {
  if (candidate.command.includes(path.sep) && !fs.existsSync(candidate.command)) {
    continue;
  }

  let failed = false;
  for (const commandArgs of commandSets) {
    const result = spawnSync(
      candidate.command,
      [...candidate.argsPrefix, "-m", "tools.map_generator.cli", ...commandArgs],
      {
        cwd: rootDir,
        stdio: "inherit",
        shell: false,
      },
    );

    if (typeof result.status === "number" && result.status === 0) {
      continue;
    }

    failed = true;
    lastFailure = result.error ?? new Error(`Python exited with status ${result.status ?? "unknown"}.`);
    break;
  }

  if (!failed) {
    process.exit(0);
  }
}

console.error(
  "Could not find a usable Python interpreter. Create .venv or install Python 3.10+ with the Windows py launcher.",
);

if (lastFailure) {
  console.error(lastFailure.message);
}

process.exit(1);

function resolvePresetCommands(mode, rest) {
  if (presetCommands[mode]) {
    if (rest.length === 0) {
      return presetCommands[mode];
    }

    if (presetCommands[mode].length === 1) {
      return [[...presetCommands[mode][0], ...rest]];
    }
  }

  return [[mode, ...rest]];
}

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

function sectionReportDir(difficulty) {
  return `public/section-reports/test-song/${difficulty}`;
}

const presetCommands = {
  analyze: [
    "analyze-sections",
    "--audio",
    "public/audio/test-song.mp3",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--output",
    "public/sections/test-song-sections.json",
  ],
  "evaluate:easy": [
    "evaluate-sections",
    "--sections",
    "public/sections/test-song-sections.json",
    "--candidates-root",
    "public/candidates/test-song/easy",
    "--difficulty",
    "easy",
    "--output-dir",
    sectionReportDir("easy"),
  ],
  "evaluate:normal": [
    "evaluate-sections",
    "--sections",
    "public/sections/test-song-sections.json",
    "--candidates-root",
    "public/candidates/test-song/normal",
    "--difficulty",
    "normal",
    "--output-dir",
    sectionReportDir("normal"),
  ],
  "evaluate:hard": [
    "evaluate-sections",
    "--sections",
    "public/sections/test-song-sections.json",
    "--candidates-root",
    "public/candidates/test-song/hard",
    "--difficulty",
    "hard",
    "--output-dir",
    sectionReportDir("hard"),
  ],
  "hybrid:easy": [
    "assemble-hybrid",
    "--sections",
    "public/sections/test-song-sections.json",
    "--section-reports-dir",
    sectionReportDir("easy"),
    "--candidates-root",
    "public/candidates/test-song/easy",
    "--difficulty",
    "easy",
    "--output-map",
    "public/maps/hybrid/test-song-easy.json",
    "--output-report",
    "public/reports/hybrid/test-song-easy-report.json",
    "--assembly-report",
    "public/hybrids/test-song-easy-assembly.json",
    "--transition-log",
    "public/hybrids/test-song-easy-transitions.json",
  ],
  "hybrid:normal": [
    "assemble-hybrid",
    "--sections",
    "public/sections/test-song-sections.json",
    "--section-reports-dir",
    sectionReportDir("normal"),
    "--candidates-root",
    "public/candidates/test-song/normal",
    "--difficulty",
    "normal",
    "--output-map",
    "public/maps/hybrid/test-song-normal.json",
    "--output-report",
    "public/reports/hybrid/test-song-normal-report.json",
    "--assembly-report",
    "public/hybrids/test-song-normal-assembly.json",
    "--transition-log",
    "public/hybrids/test-song-normal-transitions.json",
  ],
  "hybrid:hard": [
    "assemble-hybrid",
    "--sections",
    "public/sections/test-song-sections.json",
    "--section-reports-dir",
    sectionReportDir("hard"),
    "--candidates-root",
    "public/candidates/test-song/hard",
    "--difficulty",
    "hard",
    "--output-map",
    "public/maps/hybrid/test-song-hard.json",
    "--output-report",
    "public/reports/hybrid/test-song-hard-report.json",
    "--assembly-report",
    "public/hybrids/test-song-hard-assembly.json",
    "--transition-log",
    "public/hybrids/test-song-hard-transitions.json",
  ],
  all: [
    "hybrid-all",
    "--audio",
    "public/audio/test-song.mp3",
    "--analysis",
    "public/analysis/test-song-analysis.json",
    "--seed",
    "42",
  ],
  compare: [
    "compare-hybrids",
    "--hybrids-dir",
    "public/hybrids",
  ],
};

const userArgs = process.argv.slice(2);

function resolvePresetArgs(args) {
  if (args.length === 0) {
    return presetCommands.all;
  }

  const [mode, difficultyOrCommand, ...rest] = args;
  if (mode === "analyze") {
    return [...presetCommands.analyze, ...[difficultyOrCommand, ...rest].filter(Boolean)];
  }

  if (
    mode === "evaluate" &&
    ["easy", "normal", "hard"].includes(difficultyOrCommand)
  ) {
    return [
      ...presetCommands[`evaluate:${difficultyOrCommand}`],
      ...rest,
    ];
  }

  if (
    mode === "hybrid" &&
    ["easy", "normal", "hard"].includes(difficultyOrCommand)
  ) {
    return [
      ...presetCommands[`hybrid:${difficultyOrCommand}`],
      ...rest,
    ];
  }

  if (mode === "all") {
    return [...presetCommands.all, ...[difficultyOrCommand, ...rest].filter(Boolean)];
  }

  if (mode === "compare") {
    return [...presetCommands.compare, ...[difficultyOrCommand, ...rest].filter(Boolean)];
  }

  return args;
}

const normalizedArgs = resolvePresetArgs(userArgs);
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

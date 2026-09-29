import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

/**
 * Resolve a working Python interpreter for local tooling.
 *
 * Candidates are tried in order and each one is actually probed (spawned with a
 * tiny snippet) before being selected, so broken installations — including
 * stale virtualenvs whose base interpreter was uninstalled (the classic
 * "did not find executable at ...Python313\python.exe" exit-code-103 failure) —
 * are skipped automatically instead of crashing the launcher.
 *
 * Order:
 *  1. PYTHON_EXECUTABLE / PYTHON environment variable override.
 *  2. Project virtualenv (.venv), when it actually works.
 *  3. Windows py launcher with explicit versions (newest first), then bare
 *     `py`, `python`, `python3` on PATH.
 *  4. Common Windows install locations (Python314, Python313, ... oldest).
 *
 * Exits the process with a diagnostic if no usable interpreter is found.
 *
 * @param {string} projectRoot Absolute path to the project root.
 * @returns {{ command: string, args: string[], source: string, version: string }}
 */
export function resolvePythonInterpreter(projectRoot) {
  const candidates = buildPythonCandidates(projectRoot);
  const failures = [];

  for (const candidate of candidates) {
    const probe = probeInterpreter(projectRoot, candidate.command, candidate.args);
    if (probe) {
      return {
        command: candidate.command,
        args: candidate.args,
        source: candidate.source,
        version: probe.version,
      };
    }

    failures.push(`${candidate.command}${candidate.args.length ? ` ${candidate.args.join(" ")}` : ""}`);
  }

  console.error(
    [
      "Could not find a usable Python interpreter (need Python 3.10+).",
      "Tried:",
      ...failures.map((entry) => `  - ${entry}`),
      "",
      "Fix options:",
      "  - Set PYTHON_EXECUTABLE to the full path of a working python.exe.",
      "  - Rebuild the virtualenv: delete .venv, then run `py -3.14 -m venv .venv`",
      "    and `py -3.14 -m pip install -r tools/map_generator/requirements.txt`.",
      "  - Install Python from python.org (or the Microsoft Store) and ensure",
      "    the `py` launcher is on PATH.",
    ].join("\n"),
  );
  process.exit(1);
}

/**
 * Ordered list of { command, args, source } candidates.
 * @param {string} projectRoot
 */
export function buildPythonCandidates(projectRoot) {
  const candidates = [];
  const push = (command, args, source) => {
    if (command) {
      candidates.push({ command, args, source });
    }
  };

  // 1. Explicit environment override wins over everything.
  const envOverride = process.env.PYTHON_EXECUTABLE || process.env.PYTHON;
  if (envOverride && envOverride.trim()) {
    push(envOverride.trim(), [], "PYTHON_EXECUTABLE environment variable");
  }

  // 2. Project virtualenv, if present and functional. The probe protects
  //    against stale venvs whose base interpreter no longer exists.
  const venvCandidates = isWindows()
    ? [
        path.join(projectRoot, ".venv", "Scripts", "python.exe"),
        path.win32.join(projectRoot, ".venv", "Scripts", "python.exe"),
      ]
    : [path.join(projectRoot, ".venv", "bin", "python")];
  for (const venvPython of new Set(venvCandidates)) {
    push(venvPython, [], "project .venv");
  }

  // 3. py launcher with explicit versions (newest first), then generic names.
  if (isWindows()) {
    push("py", ["-3.14"], "py -3.14");
    push("py", ["-3.13"], "py -3.13");
    push("py", ["-3.12"], "py -3.12");
    push("py", ["-3.11"], "py -3.11");
    push("py", ["-3.10"], "py -3.10");
  } else {
    push("python3.14", [], "python3.14");
    push("python3", [], "python3");
  }
  push("py", [], "py");
  push("python", [], "python");

  // 4. Common Windows install locations, newest to oldest.
  if (isWindows()) {
    for (const version of ["314", "313", "312", "311", "310"]) {
      for (const base of commonWindowsPythonRoots()) {
        const pythonExe = path.join(base, `Python${version}`, "python.exe");
        // Skip obvious misses without spending a spawn on them; the probe
        // still validates anything that does exist.
        if (fs.existsSync(pythonExe)) {
          push(pythonExe, [], `install dir ${pythonExe}`);
        }
      }
    }
  }

  return candidates;
}

/**
 * Spawn `command args -c "<probe>"` and report whether it is a working Python.
 * @param {string} cwd
 * @param {string} command
 * @param {string[]} args
 */
function probeInterpreter(cwd, command, args) {
  try {
    const result = spawnSync(command, [...args, "-c", PROBE_SNIPPET], {
      cwd,
      stdio: ["ignore", "pipe", "pipe"],
      timeout: 10_000,
      windowsHide: true,
      shell: false,
      env: { ...process.env, PYTHONNOUSERSITE: "1" },
    });

    if (result.error) {
      return null;
    }

    if (typeof result.status === "number" && result.status === 0) {
      const version = result.stdout?.toString().trim().split(/\s+/)[0] ?? "";
      return { version };
    }

    return null;
  } catch {
    return null;
  }
}

const PROBE_SNIPPET = "import sys; print(sys.version.split()[0])";

function isWindows() {
  return process.platform === "win32";
}

function commonWindowsPythonRoots() {
  const roots = ["C:\\Python"];
  if (process.env.LOCALAPPDATA) {
    roots.unshift(path.join(process.env.LOCALAPPDATA, "Programs", "Python"));
  }
  if (process.env.ProgramFiles) {
    roots.push(process.env.ProgramFiles);
  }
  return roots;
}

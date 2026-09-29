import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { resolvePythonInterpreter } from "./lib/python-resolver.mjs";

const currentFile = fileURLToPath(import.meta.url);
const scriptsDir = path.dirname(currentFile);
const projectRoot = path.resolve(scriptsDir, "..");
const mode = process.argv[2] ?? "all";
const isWindows = process.platform === "win32";

const pythonPath = resolvePythonInterpreter(projectRoot);
console.log(
  `Using Python ${pythonPath.version} (${pythonPath.source}): ${pythonPath.command} ${pythonPath.args.join(" ")}`.trimEnd(),
);
const npmCommand = isWindows ? "npm.cmd" : "npm";

const children = [];
let shuttingDown = false;

if (!["all", "api", "frontend"].includes(mode)) {
  console.error(`Unsupported mode "${mode}". Use all, api, or frontend.`);
  process.exit(1);
}

if (mode === "all" || mode === "api") {
  children.push(
    spawnNamedProcess("local-api", pythonPath.command, [
      ...pythonPath.args,
      "-m",
      "uvicorn",
      "tools.local_api.app:app",
      "--host",
      "127.0.0.1",
      "--port",
      "8765",
    ]),
  );
}

if (mode === "all" || mode === "frontend") {
  children.push(
    spawnNamedProcess("generator-frontend", npmCommand, [
      "run",
      "generator:frontend",
      "--",
      "--strictPort",
    ]),
  );
}

process.on("SIGINT", () => {
  shutdown(0);
});

process.on("SIGTERM", () => {
  shutdown(0);
});

for (const child of children) {
  child.on("exit", (code, signal) => {
    if (shuttingDown) {
      return;
    }

    if (signal) {
      console.log(`Process exited from signal: ${signal}`);
      shutdown(1);
      return;
    }

    if (typeof code === "number" && code !== 0) {
      console.error(`Process exited with code ${code}.`);
      shutdown(code);
      return;
    }

    if (mode !== "all") {
      shutdown(code ?? 0);
    }
  });
}

if (mode === "all") {
  console.log("Local generator services starting...");
  console.log("API:       http://127.0.0.1:8765/api/health");
  console.log("Frontend:  http://127.0.0.1:5173/generator.html");
}

function spawnNamedProcess(name, command, args) {
  const child = spawnPortable(command, args);
  child.processName = name;
  child.on("error", (error) => {
    if (!shuttingDown) {
      console.error(`[${name}] ${error.message}`);
      shutdown(1);
    }
  });
  return child;
}

function shutdown(exitCode) {
  if (shuttingDown) {
    return;
  }

  shuttingDown = true;
  for (const child of children) {
    if (child.exitCode !== null || child.killed) {
      continue;
    }

    try {
      child.kill("SIGINT");
    } catch {
      // Ignore shutdown races and let the process exit naturally.
    }
  }

  setTimeout(() => {
    process.exit(exitCode);
  }, 150);
}

function spawnPortable(command, args) {
  if (isWindows && command.toLowerCase().endsWith(".cmd")) {
    return spawn(
      "cmd.exe",
      ["/d", "/s", "/c", buildWindowsCommand(command, args)],
      {
        cwd: projectRoot,
        env: process.env,
        stdio: "inherit",
      },
    );
  }

  return spawn(command, args, {
    cwd: projectRoot,
    env: process.env,
    stdio: "inherit",
  });
}

function buildWindowsCommand(command, args) {
  return [command, ...args].map(quoteWindowsArg).join(" ");
}

function quoteWindowsArg(value) {
  if (!/[\s"&()]/.test(value)) {
    return value;
  }

  return `"${value.replace(/"/g, '""')}"`;
}

import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const currentFile = fileURLToPath(import.meta.url);
const scriptsDir = path.dirname(currentFile);
const projectRoot = path.resolve(scriptsDir, "..");
const isWindows = process.platform === "win32";
const npmCommand = isWindows ? "npm.cmd" : "npm";
const pythonCommand = isWindows
  ? path.join(projectRoot, ".venv", "Scripts", "python.exe")
  : path.join(projectRoot, ".venv", "bin", "python");

await runStep("TypeScript generator tests", npmCommand, [
  "exec",
  "vitest",
  "run",
  "tests/generator",
]);

await runStep("Python local API tests", pythonCommand, [
  "-m",
  "unittest",
  "discover",
  "-s",
  "tools/local_api/tests",
  "-p",
  "test*.py",
]);

async function runStep(label, command, args) {
  console.log(`\n== ${label} ==`);
  await new Promise((resolve, reject) => {
    const child = spawnPortable(command, args);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }

      reject(new Error(`${label} failed with exit code ${code ?? 1}.`));
    });
    child.on("error", reject);
  });
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

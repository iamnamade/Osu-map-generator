#!/usr/bin/env python3
"""P3.3 — Unified validation & E2E test command (Phase 6 roadmap).

Runs the complete verification pass in a single, exit-code-aware invocation:

  1. Python test suite     (unittest discover, package-rooted)
       - tools/map_generator/tests   (engine, placement, rhythm, i18n, security)
       - tools/local_api/tests       (local API bridge, P0 hardening, telemetry)
  2. TypeScript typecheck  (tsc --noEmit)
  3. Vitest suite          (full frontend test suite)

The command fails fast per stage but always runs every stage so one command
gives a complete picture; the final exit code is non-zero if ANY stage failed.

Usage:
    python tools/validate_all.py            # full pass
    python tools/validate_all.py --skip-python
    python tools/validate_all.py --skip-typecheck --skip-vitest
    python tools/validate_all.py --list     # show what would run, then exit

Convenience: ``npm run validate:all`` (delegates here via package.json).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Python test roots, discovered package-rooted (top-level dir = project root)
# so the ``tools.*`` package layout is preserved and relative imports inside
# the test packages keep working. (Flat discovery re-parents test modules and
# breaks ``from .test_validation import ...`` in test_collision.py.)
PYTHON_SUITES: list[tuple[str, list[str]]] = [
    (
        "Python: tools/map_generator/tests",
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tools/map_generator/tests",
            "-t",
            ".",
            "-p",
            "test*.py",
        ],
    ),
    (
        "Python: tools/local_api/tests",
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "tools/local_api/tests",
            "-t",
            ".",
            "-p",
            "test*.py",
        ],
    ),
]

TYPECHECK_CMD: tuple[str, list[str]] = (
    "TypeScript: tsc --noEmit",
    ["tsc", "--noEmit"],
)

VITEST_CMD: tuple[str, list[str]] = (
    "Vitest: full frontend suite",
    ["vitest", "run"],
)

# Commands resolved through ``npm exec`` (package-local .bin shims).
_NODE_TOOLS = frozenset({"tsc", "vitest"})


@dataclass
class StageResult:
    label: str
    ok: bool
    duration_s: float
    detail: str


def _resolve_npm() -> str:
    """Resolve an invokable npm executable for the current platform."""
    if os.name == "nt":
        return shutil.which("npm.cmd") or shutil.which("npm") or "npm"
    return shutil.which("npm") or "npm"


def _npm_exec(command: list[str]) -> list[str]:
    """Wrap a node tool invocation in ``npm exec`` so npm resolves the
    package's local .bin shim (tsc/vitest) on every platform without a
    shell — subprocess cannot spawn .cmd files directly on Windows."""
    return [_resolve_npm(), "exec", "--yes", "--", *command]


def _run_stage(label: str, command: list[str], env_extra: dict[str, str] | None = None) -> StageResult:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)

    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    duration = time.monotonic() - started

    ok = completed.returncode == 0
    detail = (completed.stdout or "") + (completed.stderr or "")
    return StageResult(label=label, ok=ok, duration_s=duration, detail=detail)


def _stream_stage(label: str, command: list[str]) -> StageResult:
    """Run a stage streaming output live (for Vitest's progress reporting)."""
    started = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        shell=False,
    )
    duration = time.monotonic() - started
    return StageResult(
        label=label,
        ok=completed.returncode == 0,
        duration_s=duration,
        detail="",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the full validation pass: Python suite, tsc, Vitest.",
    )
    parser.add_argument("--skip-python", action="store_true", help="Skip the Python unittest suites.")
    parser.add_argument("--skip-typecheck", action="store_true", help="Skip tsc --noEmit.")
    parser.add_argument("--skip-vitest", action="store_true", help="Skip the Vitest suite.")
    parser.add_argument("--list", action="store_true", help="List the stages that would run and exit.")
    args = parser.parse_args(argv)

    stages: list[tuple[str, list[str], bool]] = []
    if not args.skip_python:
        stages.extend((label, cmd, False) for label, cmd in PYTHON_SUITES)
    if not args.skip_typecheck:
        label, cmd = TYPECHECK_CMD
        stages.append((label, cmd, True))
    if not args.skip_vitest:
        label, cmd = VITEST_CMD
        stages.append((label, cmd, False))

    if args.list:
        for label, _, _ in stages:
            print(label)
        return 0

    if not stages:
        print("Nothing to run: every stage was skipped.")
        return 1

    print("=" * 70)
    print("UNIFIED VALIDATION PASS")
    print("=" * 70)
    print(f"  Project root: {PROJECT_ROOT}")
    print(f"  Python:       {sys.executable}")
    print(f"  Stages:       {len(stages)}")
    print()

    results: list[StageResult] = []
    for index, (label, command, capture) in enumerate(stages, 1):
        print(f"[{index}/{len(stages)}] {label}")
        print("-" * 70)
        if command[0] in _NODE_TOOLS:
            # Resolve tsc/vitest through npm exec so the package's local .bin
            # shim is used on every platform without spawning a shell (Windows
            # cannot spawn .cmd shims directly via subprocess).
            command = _npm_exec(command)
        if capture:
            result = _run_stage(label, command)
            if not result.ok:
                print(result.detail.rstrip())
        else:
            result = _stream_stage(label, command)
        status = "PASS" if result.ok else "FAIL"
        print(f"  -> {status} ({result.duration_s:.1f}s)")
        print()
        results.append(result)

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for result in results:
        status = "PASS" if result.ok else "FAIL"
        print(f"  [{status}] {result.label} ({result.duration_s:.1f}s)")
    print("-" * 70)

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"RESULT: FAILED - {len(failed)}/{len(results)} stage(s) failed.")
        for result in failed:
            if result.detail.strip():
                print(f"\n--- failure detail: {result.label} ---")
                print(result.detail.rstrip()[-4000:])
        return 1

    total = sum(r.duration_s for r in results)
    print(f"RESULT: ALL PASS - {len(results)}/{len(results)} stages green in {total:.1f}s.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

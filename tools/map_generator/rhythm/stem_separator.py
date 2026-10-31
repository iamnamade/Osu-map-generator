"""AI stem separation with content-addressed caching.

Splitting a track into vocals / drums / bass / melody lets placement react to
*which instrument* is playing instead of to the mixed master.  Separation is by
far the most expensive step in the pipeline (seconds to minutes, and it wants
torch and a downloaded model), so this module is built around paying for it at
most once per audio file:

* **Content-addressed cache** -- the cache directory is named after the SHA-256
  of the audio bytes.  Re-running on the same track, or on a copy with a
  different name, reuses the stems; editing the audio produces a new key.
* **One subprocess per track** -- the backend separates all four stems in a
  single invocation; there is no per-stem process fan-out to pay for.
* **Bounded wait** -- every run has a timeout, and a failed or timed-out run
  raises rather than hanging the generator.
* **No concurrent duplicate work** -- a lock serialises runs for the same key,
  so parallel callers wait for the first result instead of separating twice.

Backends are resolved at call time, not import time: ``demucs`` is preferred
(it handles four stems natively and is the better separator), with ``spleeter``
as a fallback.  Neither is a hard dependency of the package -- when neither is
installed, :meth:`StemSeparator.separate_audio` raises an actionable error
instead of importing torch at module load.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import threading
from pathlib import Path

from ..utils import MapGeneratorError

#: Public stem keys.  ``melody`` is the backends' "other" stem.
STEM_KEYS: tuple[str, ...] = ("vocals", "drums", "bass", "melody")

#: File name each backend gives the residual stem.
_BACKEND_STEM_NAMES: dict[str, str] = {
    "vocals": "vocals",
    "drums": "drums",
    "bass": "bass",
    "other": "melody",
}

#: Default cache root.  Ignored by git (see .gitignore).
DEFAULT_STEM_DIR = ".workspaces/stems/"

#: How long a separation run may take before it is abandoned.
DEFAULT_TIMEOUT_SECONDS = 900


class StemSeparator:
    """Separate a track into four stems, caching the result on disk.

    Parameters
    ----------
    output_dir:
        Cache root.  Each track gets a subdirectory named after its content
        hash.
    backend:
        ``"demucs"``, ``"spleeter"`` or ``None`` to auto-detect.  Forcing a
        backend that is not installed raises when separating.
    timeout_seconds:
        Wall-clock limit for the backend subprocess.
    """

    def __init__(
        self,
        output_dir: str | Path = DEFAULT_STEM_DIR,
        *,
        backend: str | None = None,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.backend = backend
        self.timeout_seconds = int(timeout_seconds)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------
    @staticmethod
    def content_hash(audio_path: Path | str) -> str:
        """SHA-256 of the audio file's bytes (chunked, so memory stays flat)."""
        digest = hashlib.sha256()
        with Path(audio_path).open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def stems_directory(self, audio_path: Path | str) -> Path:
        """Cache directory for one track."""
        return self.output_dir / self.content_hash(audio_path)[:32]

    def cached_stems(self, audio_path: Path | str) -> dict[str, str] | None:
        """Return the cached stem paths, or ``None`` when incomplete/absent."""
        directory = self.stems_directory(audio_path)
        paths = {key: directory / f"{key}.wav" for key in STEM_KEYS}
        if all(path.is_file() and path.stat().st_size > 0 for path in paths.values()):
            return {key: path.as_posix() for key, path in paths.items()}
        return None

    # ------------------------------------------------------------------
    # Separation
    # ------------------------------------------------------------------
    def separate_audio(self, audio_path: str | Path) -> dict[str, str]:
        """Return ``{stem: wav_path}`` for the four stems of ``audio_path``.

        Uses the cache when the stems already exist for this exact audio
        content; otherwise runs the configured backend once and copies its
        output into the cache.
        """
        source = Path(audio_path)
        if not source.is_file():
            raise MapGeneratorError(f"Audio file for stem separation does not exist: {source}")

        cached = self.cached_stems(source)
        if cached is not None:
            return cached

        with self._lock:
            # Another caller may have finished while we waited for the lock.
            cached = self.cached_stems(source)
            if cached is not None:
                return cached
            resolved_backend = self.backend or self._detect_backend()
            if resolved_backend is None:
                raise MapGeneratorError(
                    "Stem separation needs demucs or spleeter installed "
                    "(`pip install demucs` is the smaller of the two). "
                    "Generation can run without stems by omitting the analyser."
                )

            destination = self.stems_directory(source)
            staging = destination.with_name(destination.name + ".partial")
            shutil.rmtree(staging, ignore_errors=True)
            staging.mkdir(parents=True, exist_ok=True)
            try:
                produced = self._run_backend(resolved_backend, source, staging)
                destination.mkdir(parents=True, exist_ok=True)
                for key, produced_path in produced.items():
                    shutil.copy2(produced_path, destination / f"{key}.wav")
            finally:
                shutil.rmtree(staging, ignore_errors=True)

        completed = self.cached_stems(source)
        if completed is None:  # pragma: no cover - backend wrote nothing usable
            raise MapGeneratorError(
                f"Stem separation produced incomplete output for {source}"
            )
        return completed

    # ------------------------------------------------------------------
    # Backends
    # ------------------------------------------------------------------
    @staticmethod
    def _detect_backend() -> str | None:
        """Return the first installed backend, or ``None``."""
        for name, module in (("demucs", "demucs"), ("spleeter", "spleeter")):
            if shutil.which(name) is not None:
                return name
            try:
                import importlib.util

                if importlib.util.find_spec(module) is not None:
                    return name
            except (ImportError, ValueError):  # pragma: no cover - broken install
                continue
        return None

    def _run_backend(self, backend: str, source: Path, staging: Path) -> dict[str, Path]:
        """Invoke ``backend`` once and collect its four stem files."""
        if backend == "demucs":
            command = [sys.executable, "-m", "demucs", "--out", str(staging), str(source)]
        elif backend == "spleeter":
            command = [
                sys.executable,
                "-m",
                "spleeter",
                "separate",
                "-p",
                "spleeter:4stems",
                "-o",
                str(staging),
                str(source),
            ]
        else:
            raise MapGeneratorError(f"Unknown stem separation backend: {backend}")

        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as error:
            raise MapGeneratorError(
                f"Stem separation backend '{backend}' is not runnable: {error}"
            ) from error
        except subprocess.TimeoutExpired as error:
            raise MapGeneratorError(
                f"Stem separation timed out after {self.timeout_seconds}s for {source.name}"
            ) from error

        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip().splitlines()[-3:]
            raise MapGeneratorError(
                f"Stem separation failed for {source.name} "
                f"(exit {completed.returncode}): {' | '.join(detail) or 'no output'}"
            )

        return self._collect_stems(staging, backend)

    @staticmethod
    def _collect_stems(staging: Path, backend: str) -> dict[str, Path]:
        """Find the per-stem wav files a backend wrote anywhere under ``staging``."""
        found: dict[str, Path] = {}
        for candidate in staging.rglob("*.wav"):
            stem_key = _BACKEND_STEM_NAMES.get(candidate.stem.lower())
            if stem_key is not None and stem_key not in found:
                found[stem_key] = candidate

        missing = [key for key in STEM_KEYS if key not in found]
        if missing:
            raise MapGeneratorError(
                f"Stem separation ({backend}) did not produce: {', '.join(missing)}"
            )
        return found

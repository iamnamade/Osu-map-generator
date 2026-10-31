"""Per-stem rhythm queries that drive instrument-specific object placement.

With four separated stems the engine can ask musical questions a mixed-master
analysis cannot answer: *who is playing right now?*, *how long does this vocal
line hold?*, *where exactly does the drum hit?*  The placement strategy uses
those answers to pick object type and spacing -- vocals become sliders that last
as long as the phrase, drums become jumps, bass becomes streams.

All four stems are decoded once and reduced to a shared RMS frame grid, so the
per-object queries are array lookups rather than repeated DSP:

* :meth:`get_dominant_instrument` -- mean RMS per stem inside a window.
* :meth:`get_vocal_sustain_length` -- forward walk over the vocal envelope until
  it falls below a relative threshold.
* :meth:`detect_drum_onsets` / :meth:`detect_bass_onsets` -- ``librosa`` onset
  detection on one stem only, so a snare cannot be confused with a bass pluck.

Onset lookups (:meth:`is_drum_hit`) are ``searchsorted`` on sorted arrays, which
matters because placement asks once per object.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

import numpy as np
from librosa import feature as librosa_feature
from librosa import frames_to_time as librosa_frames_to_time
from librosa import load as librosa_load
from librosa import onset as librosa_onset

#: Stems compared when deciding who leads the passage.
_DOMINANT_KEYS: tuple[str, ...] = ("vocals", "drums", "bass")

#: Fallback key when no stem has meaningful energy (intro, silence).
SILENT_INSTRUMENT = "melody"

DEFAULT_HOP_LENGTH = 512
DEFAULT_FRAME_LENGTH = 2048


class MultiStemAnalyzer:
    """Timestamp queries across the four separated stems.

    Parameters
    ----------
    stems:
        ``{"vocals": path, "drums": path, "bass": path, "melody": path}``.
        Extra keys are ignored; the three compared stems are required.
    """

    def __init__(
        self,
        stems: Mapping[str, str | Path],
        *,
        hop_length: int = DEFAULT_HOP_LENGTH,
        frame_length: int = DEFAULT_FRAME_LENGTH,
        onset_tolerance_ms: float = 60.0,
    ) -> None:
        missing = [key for key in (*_DOMINANT_KEYS, "melody") if key not in stems]
        if missing:
            raise ValueError(f"Missing stem(s) for analysis: {', '.join(missing)}")

        self.hop_length = int(hop_length)
        self.frame_length = int(frame_length)
        self.onset_tolerance_ms = float(onset_tolerance_ms)

        self.stem_paths: dict[str, str] = {key: str(value) for key, value in stems.items()}
        self._signals: dict[str, np.ndarray] = {}
        self._sample_rate = 0
        for key, path in self.stem_paths.items():
            audio, sample_rate = librosa_load(Path(path).as_posix(), sr=None, mono=True)
            if self._sample_rate == 0:
                self._sample_rate = int(sample_rate)
            self._signals[key] = np.asarray(audio, dtype=np.float32)

        # RMS envelope per stem, trimmed to the shortest stem so the shared
        # time grid is valid for all four.
        envelopes = {
            key: librosa_feature.rms(
                y=signal,
                frame_length=self.frame_length,
                hop_length=self.hop_length,
            )[0]
            for key, signal in self._signals.items()
        }
        frame_count = min(int(values.size) for values in envelopes.values())
        self._rms: dict[str, np.ndarray] = {
            key: values[:frame_count].astype(np.float64)
            for key, values in envelopes.items()
        }
        self._frame_times_ms = librosa_frames_to_time(
            np.arange(frame_count),
            sr=max(1, self._sample_rate),
            hop_length=self.hop_length,
        ) * 1_000.0
        self._frame_ms = float(self.hop_length) / max(1, self._sample_rate) * 1_000.0

        self._onsets: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------
    # Dominance
    # ------------------------------------------------------------------
    def get_dominant_instrument(self, time_ms: float, window_ms: float = 100.0) -> str:
        """Stem with the highest mean RMS in ``[time, time + window]``.

        Returns ``"vocals"``, ``"drums"``, ``"bass"`` or :data:`SILENT_INSTRUMENT`
        when every compared stem is effectively silent.
        """
        if self._frame_times_ms.size == 0:
            return SILENT_INSTRUMENT

        start = int(np.searchsorted(self._frame_times_ms, float(time_ms), side="left"))
        span = max(1, int(round(max(1.0, float(window_ms)) / max(self._frame_ms, 1e-6))))
        stop = min(self._frame_times_ms.size, start + span)
        if start >= self._frame_times_ms.size:
            start = self._frame_times_ms.size - 1
            stop = self._frame_times_ms.size

        energies = {
            key: float(np.mean(self._rms[key][start:stop]))
            for key in _DOMINANT_KEYS
        }
        leader = max(energies, key=lambda key: energies[key])
        # A tiny absolute floor keeps near-silent intros from nominating a stem.
        if energies[leader] <= 1e-7:
            return SILENT_INSTRUMENT
        return leader

    def stem_energy(self, stem: str, time_ms: float, window_ms: float = 100.0) -> float:
        """Mean RMS of ``stem`` in the window starting at ``time_ms``."""
        values = self._rms.get(stem)
        if values is None or values.size == 0:
            return 0.0
        start = int(np.searchsorted(self._frame_times_ms, float(time_ms), side="left"))
        span = max(1, int(round(max(1.0, float(window_ms)) / max(self._frame_ms, 1e-6))))
        stop = min(values.size, start + span)
        if start >= values.size:
            return float(values[-1])
        return float(np.mean(values[start:stop]))

    # ------------------------------------------------------------------
    # Sustain
    # ------------------------------------------------------------------
    def get_vocal_sustain_length(
        self,
        start_time_ms: float,
        *,
        threshold_ratio: float = 0.18,
        max_sustain_ms: float = 8_000.0,
    ) -> float:
        """How long the vocal stem keeps sounding from ``start_time_ms`` (ms).

        The threshold is relative to the stem's own 90th percentile, so a quiet
        master and a loud one yield comparable sustains.  Returns ``0.0`` when
        no vocal energy is present at the requested time.
        """
        values = self._rms.get("vocals")
        if values is None or values.size == 0 or self._frame_times_ms.size == 0:
            return 0.0

        loud = float(np.percentile(values, 90))
        threshold = max(1e-7, loud * float(threshold_ratio))

        start = int(np.searchsorted(self._frame_times_ms, float(start_time_ms), side="left"))
        if start >= values.size:
            return 0.0

        # Tolerate a few leading frames of attack before the note settles.
        lead_frames = max(1, int(round(50.0 / max(self._frame_ms, 1e-6))))
        lead = values[start : start + lead_frames]
        if lead.size and float(lead.max()) >= threshold:
            first_loud = start + int(np.argmax(lead >= threshold))
        else:
            return 0.0

        end = first_loud
        limit = int(round(float(max_sustain_ms) / max(self._frame_ms, 1e-6)))
        while end < values.size and values[end] >= threshold and (end - first_loud) < limit:
            end += 1

        duration = float(self._frame_times_ms[end - 1] - self._frame_times_ms[first_loud] + self._frame_ms)
        return float(min(max_sustain_ms, max(0.0, duration)))

    # ------------------------------------------------------------------
    # Onsets
    # ------------------------------------------------------------------
    def detect_drum_onsets(self) -> list[float]:
        """Drum-stem onset times in milliseconds, ascending."""
        return self._detect_onsets("drums")

    def detect_bass_onsets(self) -> list[float]:
        """Bass-stem onset times in milliseconds, ascending."""
        return self._detect_onsets("bass")

    def _detect_onsets(self, stem: str) -> list[float]:
        cached = self._onsets.get(stem)
        if cached is not None:
            return [float(value) for value in cached]

        signal = self._signals.get(stem)
        if signal is None or signal.size == 0 or self._sample_rate <= 0:
            self._onsets[stem] = np.empty(0, dtype=np.float64)
            return []

        try:
            times = librosa_onset.onset_detect(
                y=signal,
                sr=self._sample_rate,
                hop_length=self.hop_length,
                units="time",
                backtrack=False,
            )
        except Exception:  # pragma: no cover - librosa backend failure
            times = np.empty(0)

        array = np.sort(np.asarray(times, dtype=np.float64) * 1_000.0)
        self._onsets[stem] = array
        return [float(value) for value in array]

    def is_drum_hit(self, time_ms: float, tolerance_ms: float | None = None) -> bool:
        """Whether a detected drum onset lies within tolerance of ``time_ms``."""
        return self._has_onset(self.detect_drum_onsets(), float(time_ms), tolerance_ms)

    def is_bass_hit(self, time_ms: float, tolerance_ms: float | None = None) -> bool:
        """Whether a detected bass onset lies within tolerance of ``time_ms``."""
        return self._has_onset(self.detect_bass_onsets(), float(time_ms), tolerance_ms)

    def _has_onset(
        self,
        onsets_ms: list[float],
        time_ms: float,
        tolerance_ms: float | None,
    ) -> bool:
        if not onsets_ms:
            return False
        tolerance = self.onset_tolerance_ms if tolerance_ms is None else float(tolerance_ms)
        array = np.asarray(onsets_ms, dtype=np.float64)
        index = int(np.searchsorted(array, time_ms))
        best = np.inf
        if index < array.size:
            best = abs(float(array[index]) - time_ms)
        if index > 0 and best > tolerance:
            best = min(best, abs(float(array[index - 1]) - time_ms))
        return best <= tolerance

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def frame_times_ms(self) -> np.ndarray:
        return self._frame_times_ms

    def summary(self) -> dict[str, object]:
        """Compact description used in diagnostics."""
        counts = {key: int(values.size) for key, values in self._rms.items()}
        return {
            "sampleRate": self._sample_rate,
            "frames": int(self._frame_times_ms.size),
            "frameEnergy": {key: round(float(values.mean()), 5) for key, values in self._rms.items()},
            "onsets": {
                "drums": len(self.detect_drum_onsets()),
                "bass": len(self.detect_bass_onsets()),
            },
            "framesPerStem": counts,
        }

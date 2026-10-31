"""ML beat tracking for variable-BPM (unquantised) timing points.

Studio tracks sit on a click, so one BPM describes the whole map.  Live
recordings do not: the drummer drifts by a few milliseconds per bar and a single
red line slowly falls out of sync until the map "feels" late.  This module
follows the performance instead, emitting one red (uninherited) timing point per
measure whose beat length is measured from the *actual* beats.

Pipeline
--------
1. ``madmom``'s ``RNNBeatProcessor`` produces a beat activation function and
   ``DBNBeatTrackingProcessor`` (an HMM/dead-beat-network tracker) picks exact
   beat times from it.  This is the ML part: the tracker tolerates expressive
   timing that a fixed-tempo autocorrelation estimate cannot.
2. Beats are grouped into measures of ``meter`` beats, and each measure's beat
   length is ``(next_measure_start - this_measure_start) / meter`` -- the local
   tempo the performer actually played, not a global average.
3. The result is a list of uninherited timing-point dictionaries that the export
   layer can write straight into ``[TimingPoints]``.

Fallbacks
---------
``madmom`` is an optional, heavy dependency that does not install cleanly on
every Python/numpy combination, and importing it pulls in tensorflow-era code.
It is therefore imported *inside* the tracking call, never at module import, so
the rest of the generator keeps working without it.  When the import or the
inference fails, tracking degrades to ``librosa.beat.beat_track`` (a dynamic
programming beat tracker) and the resolved backend is recorded so callers can
report which path ran.  If neither works the caller gets a ``MapGeneratorError``
rather than an empty timing section.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from ..utils import MapGeneratorError

#: Tracking resolution expected by ``DBNBeatTrackingProcessor``.
DEFAULT_FPS = 100

#: Beats per measure for the generated red lines.
DEFAULT_METER = 4

#: osu! sample volume written into each generated timing point.
DEFAULT_VOLUME = 70

#: Local beat lengths outside this BPM band are tracking errors, not music.
MIN_BPM = 30.0
MAX_BPM = 300.0


class VariableBpmAnalyzer:
    """Track beats with ML and express them as local timing points.

    Parameters
    ----------
    audio_path:
        Source track.
    meter:
        Beats per measure; one timing point is emitted per measure.
    volume:
        Sample volume for the generated red lines.
    fps:
        Frame rate passed to the DBN tracker.
    backend:
        ``"madmom"``, ``"librosa"`` or ``None`` to auto-detect (madmom first).
    """

    def __init__(
        self,
        audio_path: str | Path,
        *,
        meter: int = DEFAULT_METER,
        volume: int = DEFAULT_VOLUME,
        fps: int = DEFAULT_FPS,
        backend: str | None = None,
    ) -> None:
        self.audio_path = Path(audio_path)
        self.meter = max(1, int(meter))
        self.volume = int(volume)
        self.fps = int(fps)
        self.backend = backend

        #: Backend that actually produced the beats ("madmom" / "librosa").
        self.resolved_backend: str | None = None
        self._beats_ms: list[float] | None = None
        self._timing_points: list[dict[str, Any]] | None = None
        self._point_times = np.empty(0, dtype=np.float64)
        self._point_lengths = np.empty(0, dtype=np.float64)

    # ------------------------------------------------------------------
    # Beat extraction
    # ------------------------------------------------------------------
    def extract_exact_beats(self) -> list[float]:
        """Exact beat timestamps in milliseconds, ascending.

        Uses madmom when available (and permitted by ``backend``), otherwise
        falls back to librosa's dynamic-programming tracker.
        """
        if self._beats_ms is not None:
            return list(self._beats_ms)

        if not self.audio_path.is_file():
            raise MapGeneratorError(f"Audio file for beat tracking does not exist: {self.audio_path}")

        beats, backend = self._track_beats()
        # The trackers report seconds; every public API here is milliseconds, so
        # convert once before filtering (a seconds/ms mix silently discards most
        # beats and writes nonsense beat lengths).
        beats_ms = np.asarray(beats, dtype=np.float64).ravel() * 1_000.0
        cleaned: list[float] = []
        previous = -math.inf
        for value in beats_ms:
            if not math.isfinite(float(value)):
                continue
            moment = float(value)
            # Beats must strictly advance; sub-millisecond duplicates are tracker noise.
            if moment > previous + 1.0:
                cleaned.append(round(moment, 3))
                previous = moment

        if len(cleaned) < 2:
            raise MapGeneratorError(
                f"Beat tracking produced {len(cleaned)} usable beat(s) for {self.audio_path.name}"
            )

        self.resolved_backend = backend
        self._beats_ms = cleaned
        return list(cleaned)

    def _track_beats(self) -> tuple[np.ndarray, str]:
        """Return beat times in **seconds** plus the backend that produced them."""
        order = [self.backend] if self.backend else ["madmom", "librosa"]
        errors: list[str] = []
        for candidate in order:
            try:
                if candidate == "madmom":
                    return self._madmom_beats(), "madmom"
                if candidate == "librosa":
                    return self._librosa_beats(), "librosa"
                errors.append(f"unknown backend {candidate!r}")
            except Exception as error:  # noqa: BLE001 - optional heavy dependency
                errors.append(f"{candidate}: {error}")
        raise MapGeneratorError(
            "Beat tracking failed; install madmom (`pip install madmom`) or librosa. "
            + " | ".join(errors)
        )

    def _madmom_beats(self) -> np.ndarray:
        """madmom RNN activation + DBN tracker (imported lazily; heavy)."""
        from madmom.features.beats import (  # type: ignore[import-not-found]
            DBNBeatTrackingProcessor,
            RNNBeatProcessor,
        )

        activations = RNNBeatProcessor()(self.audio_path.as_posix())
        tracker = DBNBeatTrackingProcessor(fps=self.fps)
        return np.asarray(tracker(activations), dtype=np.float64)

    def _librosa_beats(self) -> np.ndarray:
        """Fallback: librosa dynamic-programming beat tracker."""
        from librosa import beat as librosa_beat
        from librosa import frames_to_time as librosa_frames_to_time
        from librosa import load as librosa_load

        samples, sample_rate = librosa_load(self.audio_path.as_posix(), sr=22050, mono=True)
        _, frames = librosa_beat.beat_track(
            y=samples, sr=sample_rate, units="frames", trim=False
        )
        return np.asarray(
            librosa_frames_to_time(np.asarray(frames), sr=sample_rate), dtype=np.float64
        )

    # ------------------------------------------------------------------
    # Timing points
    # ------------------------------------------------------------------
    def generate_timing_points(self) -> list[dict[str, Any]]:
        """One uninherited timing point per measure, at the local tempo.

        The beat length is ``(next_measure_start - current_measure_start) /
        meter``: the measured duration of the four beats that follow, so a bar
        that was played 5 ms fast gets its own faster red line instead of
        dragging the error forward.
        """
        if self._timing_points is not None:
            return [dict(point) for point in self._timing_points]

        beats = self.extract_exact_beats()
        if len(beats) <= self.meter:
            raise MapGeneratorError(
                f"Need more than {self.meter} beats to measure a measure; got {len(beats)}"
            )

        points: list[dict[str, Any]] = []
        index = 0
        while index + self.meter < len(beats):
            current = beats[index]
            following = beats[index + self.meter]
            measured = (following - current) / float(self.meter)
            beat_length = self._validate(measured)
            if beat_length is not None:
                points.append(self._point(current, beat_length))
            index += self.meter

        # Trailing beats that never closed a full measure still need a tempo:
        # reuse the final measured beat length rather than dropping the tail.
        if points and index < len(beats):
            points.append(self._point(beats[index], points[-1]["beatLength"]))

        if not points:
            raise MapGeneratorError("No measure-length beat spans were found in the track")

        self._timing_points = points
        self._point_times = np.asarray([p["time"] for p in points], dtype=np.float64)
        self._point_lengths = np.asarray([p["beatLength"] for p in points], dtype=np.float64)
        return [dict(point) for point in points]

    def _point(self, time_ms: float, beat_length: float) -> dict[str, Any]:
        return {
            "time": round(float(time_ms), 3),
            "beatLength": round(float(beat_length), 3),
            "meter": self.meter,
            "uninherited": 1,
            "volume": self.volume,
        }

    def _validate(self, beat_length_ms: float) -> float | None:
        """Reject physically impossible local tempos (tracker glitches)."""
        if not math.isfinite(beat_length_ms) or beat_length_ms <= 0:
            return None
        bpm = 60_000.0 / beat_length_ms
        if bpm < MIN_BPM or bpm > MAX_BPM:
            return None
        return float(beat_length_ms)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def beat_length_at(self, time_ms: float) -> float:
        """Local beat length (ms per beat) active at ``time_ms``.

        This is what distance snap and slider-velocity maths should use: the
        tempo of the measure the object lands in, not a map-wide constant.
        """
        if self._point_times.size == 0:
            self.generate_timing_points()
        index = int(np.searchsorted(self._point_times, float(time_ms), side="right")) - 1
        index = max(0, min(index, self._point_lengths.size - 1))
        return float(self._point_lengths[index])

    def bpm_at(self, time_ms: float) -> float:
        """Local BPM at ``time_ms``."""
        beat_length = self.beat_length_at(time_ms)
        return 60_000.0 / beat_length if beat_length > 0 else 0.0

    def to_osu_lines(self) -> list[str]:
        """Render the generated points as ``[TimingPoints]`` lines.

        Format: ``time,beatLength,meter,sampleSet,sampleIndex,volume,uninherited,effects``.
        """
        return [
            f"{point['time']},{point['beatLength']},{point['meter']},2,{point['volume']},1,0"
            for point in self.generate_timing_points()
        ]

    def summary(self) -> dict[str, Any]:
        """Diagnostics for the generator payload."""
        points = self.generate_timing_points()
        beat_lengths = [point["beatLength"] for point in points]
        return {
            "backend": self.resolved_backend or "unknown",
            "measures": len(points),
            "bpmMin": round(60_000.0 / max(beat_lengths), 2),
            "bpmMax": round(60_000.0 / min(beat_lengths), 2),
            "driftMs": round(max(beat_lengths) - min(beat_lengths), 3),
        }

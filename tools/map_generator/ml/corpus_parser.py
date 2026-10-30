"""Corpus parsing for mapper-style cloning.

Turns a directory of existing ``.osu`` files into sequences of discrete
pattern states that a Markov model can learn from.  The idea is to stop
hand-writing placement heuristics and instead learn what a specific mapper
actually does: how long they leave between objects, how far the cursor
travels, and how sharply they turn.

State encoding
--------------
Each transition between consecutive objects is described by three numbers:

``delta_beats``
    Rhythm gap to the previous object, snapped to a musical subdivision
    (1/8, 1/6, 1/4, 1/3, 1/2, 2/3, 3/4, 1, 4/3, 3/2, 2, 8/3, 3, 4, 6, 8).

``spacing``
    Euclidean cursor travel, normalised into *beats of travel* and quantised
    so it can serve as a dictionary key.  Normalisation divides out both the
    timing section's slider velocity and the beatmap's SliderMultiplier, so a
    1.4x-SV map and a 0.8x-SV map produce comparable spacings.

``angle_bin``
    Signed turn angle from the incoming heading to the outgoing heading, in
    ``0..ANGLE_BIN_COUNT-1`` bins of :data:`ANGLE_BIN_DEGREES` degrees, where
    bin ``ANGLE_BIN_COUNT // 2`` is a dead-straight line.  Limb ordering
    preserves the mapper's left/right handedness.

States are ``NamedTuple``s, so they are hashable and sortable, which lets the
Markov model use them directly as dictionary keys and index them
deterministically.

Objects the state chain cannot describe are skipped rather than faked:
spinners (they carry no cursor position) and zero-length steps (stacked
objects, where no heading exists).
"""

from __future__ import annotations

import math
from bisect import bisect_right
from pathlib import Path
from typing import Any, NamedTuple

from ..utils import MapGeneratorError

#: osu! playfield scale: pixels travelled per beat at 1.0x slider velocity.
PIXELS_PER_BEAT = 100.0

#: Musical subdivisions a rhythm gap may snap to, expressed in beats.
GAP_DIVISIONS: tuple[float, ...] = (
    1.0 / 8.0,
    1.0 / 6.0,
    1.0 / 4.0,
    1.0 / 3.0,
    1.0 / 2.0,
    2.0 / 3.0,
    3.0 / 4.0,
    1.0,
    4.0 / 3.0,
    3.0 / 2.0,
    2.0,
    8.0 / 3.0,
    3.0,
    4.0,
    6.0,
    8.0,
)

#: Trajectory turns are bucketed into 15-degree bins covering -180..180.
ANGLE_BIN_COUNT = 24
ANGLE_BIN_DEGREES = 15.0

#: Spacing is quantised to quarter-beat steps by default.
DEFAULT_SPACING_QUANTUM = 0.25

#: Upper bound for a normalised spacing, in beats of travel.
MAX_SPACING_BEATS = 16.0

#: Guard for the degenerate "objects stacked on one pixel" case.
_MIN_SEGMENT_PX = 1e-3


class PatternState(NamedTuple):
    """One discretised transition in a mapper's pattern chain."""

    delta_beats: float
    spacing: float
    angle_bin: int

    def to_tuple(self) -> tuple[float, float, int]:
        """Return the plain tuple form (useful for reporting/serialisation)."""
        return (self.delta_beats, self.spacing, self.angle_bin)


def quantize_spacing(value: float, quantum: float = DEFAULT_SPACING_QUANTUM) -> float:
    """Snap ``value`` to the nearest multiple of ``quantum``."""
    if quantum <= 0:
        return round(value, 4)
    return round(round(value / quantum) * quantum, 4)


def quantize_gap_beats(delta_ms: float, beat_length_ms: float) -> float:
    """Snap a millisecond gap to the nearest musical subdivision in beats."""
    if beat_length_ms <= 0:
        return GAP_DIVISIONS[0]
    ratio = delta_ms / beat_length_ms
    nearest = min(GAP_DIVISIONS, key=lambda division: abs(division - ratio))
    return float(round(nearest, 4))


def quantize_angle(turn_degrees: float) -> int:
    """Bucket a signed turn angle into a discrete bin index."""
    raw_bin = int(round(turn_degrees / ANGLE_BIN_DEGREES))
    # Signed bins run -12..12; shift so 0 is the most negative turn.
    return (raw_bin + ANGLE_BIN_COUNT // 2) % ANGLE_BIN_COUNT


def angle_bin_to_degrees(angle_bin: int) -> float:
    """Invert :func:`quantize_angle`, returning the bin's centre in degrees."""
    return (angle_bin - ANGLE_BIN_COUNT // 2) * ANGLE_BIN_DEGREES


def _normalise_degrees(angle: float) -> float:
    while angle <= -180.0:
        angle += 360.0
    while angle > 180.0:
        angle -= 360.0
    return angle


class _TimingMap:
    """Resolve beat length and slider velocity at an arbitrary timestamp.

    ``.osu`` timing points are a step function: the active value is the last
    point at or before the timestamp.  Sorted timestamp lists plus
    ``bisect_right`` keep this O(log n) per lookup instead of rescanning the
    section for every object.
    """

    def __init__(self, timing_points: list[Any], slider_multiplier: float) -> None:
        self.slider_multiplier = slider_multiplier
        uninherited = [
            point for point in timing_points
            if getattr(point, "uninherited", 0) and getattr(point, "beat_length", 0) > 0
        ]
        inherited = [
            point for point in timing_points
            if not getattr(point, "uninherited", 0) and getattr(point, "beat_length", 0) < 0
        ]
        uninherited.sort(key=lambda point: point.time)
        inherited.sort(key=lambda point: point.time)

        self._beat_times = [point.time for point in uninherited]
        self._beat_lengths = [float(point.beat_length) for point in uninherited]
        self._sv_times = [point.time for point in inherited]
        # osu! stores SV as a negative beat length: multiplier = -100 / beat_length.
        self._sv_values = [
            min(10.0, max(0.1, -100.0 / float(point.beat_length))) for point in inherited
        ]

    @property
    def has_timing(self) -> bool:
        return bool(self._beat_lengths)

    def beat_length_at(self, time_ms: float) -> float | None:
        if not self._beat_lengths:
            return None
        index = bisect_right(self._beat_times, time_ms) - 1
        if index < 0:
            index = 0
        return self._beat_lengths[index]

    def sv_multiplier_at(self, time_ms: float) -> float:
        if not self._sv_values:
            return 1.0
        index = bisect_right(self._sv_times, time_ms) - 1
        if index < 0:
            return 1.0
        return self._sv_values[index]

    def pixels_per_beat_at(self, time_ms: float) -> float:
        """Cursor travel of one beat at this timestamp, in pixels."""
        return PIXELS_PER_BEAT * self.slider_multiplier * self.sv_multiplier_at(time_ms)


class OsuCorpusParser:
    """Parse ``.osu`` files into sequences of :class:`PatternState`.

    Parameters
    ----------
    spacing_quantum:
        Spacing bucket width, in beats of travel.
    min_sequence_length:
        Sequences shorter than this are dropped; a single state carries no
        transition information.
    """

    def __init__(
        self,
        *,
        spacing_quantum: float = DEFAULT_SPACING_QUANTUM,
        min_sequence_length: int = 2,
    ) -> None:
        self.spacing_quantum = spacing_quantum
        self.min_sequence_length = min_sequence_length
        #: Diagnostics from the most recent ``parse_directory`` call.
        self.report: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Directory entry point
    # ------------------------------------------------------------------
    def parse_directory(self, dir_path: str) -> list[list[PatternState]]:
        """Parse every ``.osu`` file in ``dir_path``.

        Returns one state sequence per usable file.  Unparseable or empty maps
        are reported in :attr:`report` and skipped rather than aborting the
        scan, so one corrupt file cannot poison a whole training corpus.
        """
        folder = Path(dir_path)
        if not folder.exists():
            raise MapGeneratorError(f"Corpus directory does not exist: {dir_path}")
        if not folder.is_dir():
            raise MapGeneratorError(f"Corpus path is not a directory: {dir_path}")

        files = sorted(
            (path for path in folder.iterdir() if path.suffix.lower() == ".osu"),
            key=lambda path: path.name.lower(),
        )

        sequences: list[list[PatternState]] = []
        warnings: list[str] = []
        parsed_files = 0
        total_states = 0

        for path in files:
            try:
                sequence = self.parse_file(path)
            except MapGeneratorError as error:
                warnings.append(f"{path.name}: {error}")
                continue
            except OSError as error:
                warnings.append(f"{path.name}: unreadable ({error})")
                continue

            parsed_files += 1
            total_states += len(sequence)
            if len(sequence) < self.min_sequence_length:
                warnings.append(
                    f"{path.name}: only {len(sequence)} state(s), below the "
                    f"minimum of {self.min_sequence_length}"
                )
                continue
            sequences.append(sequence)

        self.report = {
            "directory": folder.as_posix(),
            "filesScanned": len(files),
            "filesParsed": parsed_files,
            "sequences": len(sequences),
            "states": total_states,
            "warnings": warnings,
        }
        return sequences

    # ------------------------------------------------------------------
    # Single-file entry point
    # ------------------------------------------------------------------
    def parse_file(self, path: Path | str) -> list[PatternState]:
        """Parse one ``.osu`` file into its pattern-state sequence."""
        # Imported lazily: the osu_format package re-exports the whole export
        # pipeline, and the placement engine imports this module.
        from ..osu_format.parser import parse_osu_file

        beatmap = parse_osu_file(Path(path))

        try:
            slider_multiplier = float(beatmap.difficulty.get("SliderMultiplier", "1.4"))
        except (TypeError, ValueError):
            slider_multiplier = 1.4
        if slider_multiplier <= 0:
            slider_multiplier = 1.4

        timing = _TimingMap(list(beatmap.timing_points), slider_multiplier)
        if not timing.has_timing:
            raise MapGeneratorError("no uninherited timing point, so no beat grid")

        # Spinners carry no cursor position, so they cannot seed a transition.
        points: list[tuple[int, int, int]] = [
            (int(circle.time), int(circle.x), int(circle.y)) for circle in beatmap.circles
        ]
        points.extend(
            (int(slider.time), int(slider.x), int(slider.y))
            for slider in beatmap.sliders
        )
        points.sort(key=lambda entry: entry[0])

        states: list[PatternState] = []
        for index in range(2, len(points)):
            previous_time, previous_x, previous_y = points[index - 2]
            current_time, current_x, current_y = points[index - 1]
            next_time, next_x, next_y = points[index]

            incoming_x = current_x - previous_x
            incoming_y = current_y - previous_y
            outgoing_x = next_x - current_x
            outgoing_y = next_y - current_y
            incoming_length = math.hypot(incoming_x, incoming_y)
            outgoing_length = math.hypot(outgoing_x, outgoing_y)
            if incoming_length < _MIN_SEGMENT_PX or outgoing_length < _MIN_SEGMENT_PX:
                continue

            delta_ms = next_time - current_time
            beat_length = timing.beat_length_at(float(current_time))
            if delta_ms <= 0 or beat_length is None or beat_length <= 0:
                continue

            pixels_per_beat = timing.pixels_per_beat_at(float(current_time))
            if pixels_per_beat <= 0:
                continue

            spacing_beats = min(outgoing_length / pixels_per_beat, MAX_SPACING_BEATS)

            incoming_degrees = math.degrees(math.atan2(incoming_y, incoming_x))
            outgoing_degrees = math.degrees(math.atan2(outgoing_y, outgoing_x))
            turn = _normalise_degrees(outgoing_degrees - incoming_degrees)

            states.append(
                PatternState(
                    delta_beats=quantize_gap_beats(delta_ms, beat_length),
                    spacing=quantize_spacing(spacing_beats, self.spacing_quantum),
                    angle_bin=quantize_angle(turn),
                )
            )

        return states

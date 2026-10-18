"""Slider-velocity calibration for free-form sliders.

Ported from ``osu-dreamer`` ``osu_dreamer/data/beatmap/decode.py``
(see ``docs/OSU_DREAMER_FORENSIC_ANALYSIS.md`` §7.4).

Problem: a generator that picks slider length (px) and slider duration (ms) independently has
to emit *one* uninherited timing point (beat length) plus inherited points that make every
slider's real duration match its geometry. osu!'s relation is

    duration_one_slide = length / (slider_mult * 100) * beat_length

so the implied path velocity of a slider with ``slides`` repeats over ``duration`` ms is

    velocity = length * slides / duration          [px/ms]

and the inherited-point multiplier must be ``SV = velocity / base_velocity`` where
``base_velocity = slider_mult * 100 / beat_length``.

Choosing ``base_velocity`` as the **geometric mean** of the observed velocities minimises
``max_i |log SV_i|`` and therefore keeps the most sliders inside osu!'s ``[0.1, 10]`` clamp.
(A sliders-less map cannot be calibrated; upstream silently defaults to 600 BPM — we raise.)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Sequence

#: osu! hard clamp on inherited-point slider velocity multipliers.
MIN_SV = 0.1
MAX_SV = 10.0


@dataclass(frozen=True)
class SliderTiming:
    """One slider's geometry and duration, in the units osu! cares about."""

    time_ms: int
    length: float  # px, one slide
    slides: int  # 1 == no repeats
    duration_ms: float  # total time from start to end, all repeats


@dataclass(frozen=True)
class TimingCalibration:
    """A beat length plus one inherited SV per slider."""

    beat_length_ms: float
    base_velocity: float
    sv: tuple[float, ...]

    @property
    def bpm(self) -> float:
        return 60_000.0 / self.beat_length_ms

    def clamped_count(self, sliders: Sequence[SliderTiming]) -> int:
        """How many sliders needed clamping (0 means the geometry is self-consistent)."""
        raw = [s.length * s.slides / s.duration_ms / self.base_velocity for s in sliders]
        return sum(1 for v in raw if not (MIN_SV <= v <= MAX_SV))


def synthesise_timing(
    sliders: Iterable[SliderTiming],
    slider_mult: float = 1.0,
) -> TimingCalibration:
    """Calibrate one beat length + per-slider SV from slider geometry.

    Raises:
        ValueError: no sliders, or a slider with a non-positive duration/shape. Upstream
            falls back to ``beat_length = 100`` (600 BPM) instead; that produces maps whose
            objects are mis-timed against any real grid, so it is rejected here.
    """
    sliders = list(sliders)
    if not sliders:
        raise ValueError("cannot synthesise timing without sliders")
    if slider_mult <= 0:
        raise ValueError(f"slider_mult must be positive, got {slider_mult}")

    velocities: list[float] = []
    for s in sliders:
        if s.length <= 0:
            raise ValueError(f"slider at {s.time_ms}ms has non-positive length {s.length}")
        if s.slides < 1:
            raise ValueError(f"slider at {s.time_ms}ms has invalid repeat count {s.slides}")
        if s.duration_ms <= 0:
            raise ValueError(f"slider at {s.time_ms}ms has non-positive duration {s.duration_ms}")
        velocities.append(s.length * s.slides / s.duration_ms)

    base_velocity = math.sqrt(min(velocities) * max(velocities))
    beat_length = slider_mult * 100.0 / base_velocity
    sv = tuple(min(MAX_SV, max(MIN_SV, v / base_velocity)) for v in velocities)
    return TimingCalibration(beat_length_ms=beat_length, base_velocity=base_velocity, sv=sv)


def path_velocity(length_px: float, repeats: int, duration_ms: float) -> float:
    """Cursor speed implied by a slider's geometry, in px/ms, across all repeats."""
    if duration_ms <= 0:
        raise ValueError(f"slider duration must be positive, got {duration_ms}")
    return float(length_px) * max(1, int(repeats)) / float(duration_ms)


def base_slider_velocity(slider_mult: float, beat_length_ms: float) -> float:
    """Speed a slider with SV = 1 travels under the given tempo, in px/ms.

    osu!'s relation ``slide_duration = length / (slider_mult * 100) * beat_length``
    inverts to ``base_velocity = slider_mult * 100 / beat_length``.
    """
    if slider_mult <= 0:
        raise ValueError(f"slider_mult must be positive, got {slider_mult}")
    if beat_length_ms <= 0:
        raise ValueError(f"beat_length must be positive, got {beat_length_ms}")
    return slider_mult * 100.0 / beat_length_ms


def sv_multiplier(velocity: float, base_velocity: float) -> float:
    """Inherited-point multiplier for a slider, clamped to osu!'s supported range."""
    if base_velocity <= 0:
        raise ValueError(f"base velocity must be positive, got {base_velocity}")
    return min(MAX_SV, max(MIN_SV, velocity / base_velocity))


def dedupe_sv_lines(
    sliders: Sequence[SliderTiming],
    calibration: TimingCalibration,
) -> list[tuple[int, float]]:
    """Green lines to emit, de-duplicated by ``(timestamp, SV)``.

    Upstream emits one inherited point per slider, which on a dense map means hundreds of
    timing points for a handful of distinct velocities. Emitting only the transitions keeps
    the .osu editable.
    """
    if len(sliders) != len(calibration.sv):
        raise ValueError("sliders and calibration.sv length mismatch")

    lines: list[tuple[int, float]] = []
    last: float | None = None
    for slider, sv in zip(sliders, calibration.sv):
        if last is None or abs(sv - last) > 1e-9:
            lines.append((int(slider.time_ms), round(sv, 3)))
            last = sv
    return lines

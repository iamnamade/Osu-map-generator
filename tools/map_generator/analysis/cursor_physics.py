"""Virtual cursor auto-play simulation and strain-based star prediction.

Before a map is packaged, an actual player has to hit every object.  This module
walks the generated coordinates the way a cursor would -- one object at a time --
and asks two questions the placement engines cannot:

* **Can a human reach it?**  Each consecutive pair yields a cursor velocity in
  pixels per millisecond.  Anything above :data:`MAX_CURSOR_VELOCITY_PX_PER_MS`
  is flagged as unplayable, so the caller can nerf the jump instead of shipping
  a map that cannot be passed.
* **How hard does it feel?**  Aim and speed strain accumulate per movement and
  decay exponentially with the time gap, so a stream of quick jumps builds
  pressure while a rest bleeds it off.  The highest strain peaks are extracted
  osu!-style and mapped onto a predicted star rating.

Why this is not the difficulty package
--------------------------------------
``difficulty/`` scores an already-exported map against audio analysis, phrase
structure and pattern diagnostics.  This module is deliberately narrower: pure
geometry and timing, no audio, so it can run inside generation on a plain list
of ``to_dict()`` payloads and be cheap enough to repeat after a nerf pass.

Performance
-----------
Parsing and the per-pair geometry are vectorised numpy operations; the strain
recurrence is the only inherently sequential part and runs a single pass over
preallocated arrays.  Peak extraction uses a monotonic deque sliding-window
maximum, so the whole simulation is O(N) apart from the final peak sort.

A spinner carries no cursor position: the player may reposition freely while it
spins, so the pair spanning a spinner is treated as a break (no velocity check,
no strain) rather than an impossible teleport.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Mapping, Sequence

import numpy as np

#: Human cursor speed ceiling in pixels per millisecond (~12 px/ms is the point
#: where a jump stops being physically reachable, not merely hard).
MAX_CURSOR_VELOCITY_PX_PER_MS = 12.0

#: Strain half-life style decay constants, in milliseconds.  Aim holds its value
#: longer than speed: the arm keeps carrying momentum through a short rest, while
#: tapping speed resets much faster.
AIM_DECAY_MS = 320.0
SPEED_DECAY_MS = 180.0

#: Sliding window, in movements, used when extracting strain peaks.  A window
#: rather than single movements keeps sparse maps from scoring on one lucky jump.
PEAK_WINDOW = 5
#: Fraction of the strongest windows that contribute to the final strain value.
PEAK_FRACTION = 0.25

#: Saturating scales for the star mapping.  These are calibration constants, not
#: physical laws; they were fitted so uniform reference patterns read the way
#: they do in game: 150 px jumps every 250 ms land near 3.5 stars, a 100 px /
#: 180 ms stream near 4.5, and a 100 px / 140 ms stream near 6.1.  Treat the
#: output as a comparative estimate, not an official SR.
AIM_STAR_CEILING = 5.2  # peak aim strain (px/ms) treated as 10 stars
SPEED_STAR_CEILING_PER_S = 20.0  # peak speed strain (1/s) treated as 10 stars
STAR_EXPONENT = 0.72
AIM_WEIGHT = 0.55
SPEED_WEIGHT = 0.45

#: Share of the allowed travel a nerfed jump keeps, leaving headroom for the
#: integer coordinate rounding that follows.
NERF_SAFETY = 0.9

_PLAYFIELD_WIDTH = 512.0
_PLAYFIELD_HEIGHT = 384.0


class AutoPlaySimulator:
    """Simulate a cursor playing through the generated hit objects.

    Parameters
    ----------
    max_velocity:
        Cursor speed ceiling in pixels per millisecond above which a jump is
        reported as unplayable.
    """

    def __init__(self, *, max_velocity: float = MAX_CURSOR_VELOCITY_PX_PER_MS) -> None:
        self.max_velocity = float(max_velocity)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def simulate_playthrough(self, hit_objects: list[dict]) -> dict:
        """Walk every object and report playability plus a predicted star rating.

        Args:
            hit_objects: Object payloads as emitted by ``to_dict()``, in play
                order.  Entries need ``time`` and, for anything but a spinner,
                ``x`` / ``y``.  Missing or non-positional entries are skipped.

        Returns:
            A JSON-serialisable dict with ``playable``, ``status``,
            ``predictedStarRating`` and the strain/velocity detail behind it.
        """
        chain = self._movement_chain(hit_objects)
        if not chain.times.size:
            return self._empty_report(len(hit_objects))

        distances, deltas, breaks = self._movement_metrics(chain)
        velocities = np.divide(
            distances,
            deltas,
            out=np.zeros_like(distances),
            where=deltas > 0,
        )
        # A pair spanning a spinner is not a cursor movement at all.
        velocities = np.where(breaks, 0.0, velocities)

        offenders = self._collect_offenders(chain, distances, deltas, velocities, breaks)
        aim_strain, speed_strain = self._strain_series(distances, deltas, breaks)

        aim_peak = _weighted_peak_average(_sliding_peak(aim_strain, PEAK_WINDOW), PEAK_FRACTION)
        speed_peak = _weighted_peak_average(_sliding_peak(speed_strain, PEAK_WINDOW), PEAK_FRACTION)

        aim_stars = 10.0 * min(1.0, aim_peak / AIM_STAR_CEILING) ** STAR_EXPONENT
        speed_stars = 10.0 * min(
            1.0, (speed_peak * 1000.0) / SPEED_STAR_CEILING_PER_S
        ) ** STAR_EXPONENT
        predicted = _clamp(AIM_WEIGHT * aim_stars + SPEED_WEIGHT * speed_stars, 0.0, 10.0)

        max_velocity = float(velocities.max()) if velocities.size else 0.0
        playable = not offenders

        return {
            "playable": playable,
            "status": "Playable" if playable else "Unplayable/Requires Nerf",
            "predictedStarRating": round(predicted, 2),
            "aimStarRating": round(aim_stars, 2),
            "speedStarRating": round(speed_stars, 2),
            "aimPeakStrain": round(aim_peak, 4),
            "speedPeakStrain": round(speed_peak, 5),
            "maxCursorVelocityPxPerMs": round(max_velocity, 3),
            "velocityLimitPxPerMs": round(self.max_velocity, 3),
            "objectCount": len(hit_objects),
            "movementCount": int(distances.size),
            "unplayableObjects": offenders,
        }

    def nerf_unplayable(self, hit_objects: list[dict]) -> tuple[list[dict], int]:
        """Pull unplayable jumps back within the cursor speed limit.

        The offending object is moved along the line toward the previous one, so
        its direction (the mapper's intent) is preserved while the distance is
        shortened to what a cursor can cover in the available time.  Objects are
        visited in play order, so a nerfed position becomes the anchor for the
        next pair -- the same chain the simulator will re-measure.

        Returns:
            ``(updated_payloads, nerfed_count)``.  The list is aligned 1:1 with
            the input; spinners and untouched objects are copied unchanged.
        """
        updated: list[dict] = [
            dict(item) if isinstance(item, Mapping) else item for item in hit_objects
        ]
        chain = self._movement_chain(updated)
        if chain.times.size < 2:
            return updated, 0

        nerfed = 0
        previous_x = chain.xs[0]
        previous_y = chain.ys[0]
        spinner_times = _spinner_times(updated)

        for node in range(1, chain.times.size):
            time_ms = int(chain.times[node])
            current_x = float(chain.xs[node])
            current_y = float(chain.ys[node])
            delta_ms = float(chain.times[node] - chain.times[node - 1])

            if _spans_spinner(spinner_times, float(chain.times[node - 1]), time_ms):
                # Free repositioning during a spinner; nothing to nerf.
                previous_x, previous_y = current_x, current_y
                continue

            if delta_ms > 0:
                distance = math.hypot(current_x - previous_x, current_y - previous_y)
                velocity = distance / delta_ms
                if velocity > self.max_velocity:
                    allowed = self.max_velocity * delta_ms * NERF_SAFETY
                    if distance > 1e-9:
                        scale = allowed / distance
                        current_x = previous_x + (current_x - previous_x) * scale
                        current_y = previous_y + (current_y - previous_y) * scale
                    else:
                        current_x, current_y = previous_x, previous_y
                    current_x = _clamp(current_x, 0.0, _PLAYFIELD_WIDTH)
                    current_y = _clamp(current_y, 0.0, _PLAYFIELD_HEIGHT)

                    payload = updated[chain.indices[node]]
                    payload["x"] = int(round(current_x))
                    payload["y"] = int(round(current_y))
                    nerfed += 1

            previous_x, previous_y = current_x, current_y

        return updated, nerfed

    # ------------------------------------------------------------------
    # Chain extraction
    # ------------------------------------------------------------------
    def _movement_chain(self, hit_objects: Sequence[Any]) -> "_Chain":
        """Collect positional objects in play order into flat arrays."""
        times: list[int] = []
        xs: list[float] = []
        ys: list[float] = []
        indices: list[int] = []

        for index, item in enumerate(hit_objects):
            if not isinstance(item, Mapping):
                continue
            if str(item.get("type", "circle")) == "spinner":
                continue
            x = item.get("x")
            y = item.get("y")
            time_ms = item.get("time")
            if x is None or y is None or time_ms is None:
                continue
            try:
                times.append(int(time_ms))
                xs.append(float(x))
                ys.append(float(y))
            except (TypeError, ValueError):
                continue
            indices.append(index)

        if len(times) > 1 and any(times[i] < times[i - 1] for i in range(1, len(times))):
            order = sorted(range(len(times)), key=lambda position: times[position])
            times = [times[position] for position in order]
            xs = [xs[position] for position in order]
            ys = [ys[position] for position in order]
            indices = [indices[position] for position in order]

        return _Chain(
            times=np.asarray(times, dtype=np.int64),
            xs=np.asarray(xs, dtype=np.float64),
            ys=np.asarray(ys, dtype=np.float64),
            indices=indices,
            spinners=_spinner_times(hit_objects),
        )

    def _movement_metrics(self, chain: "_Chain") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Per-pair distance, time delta and spinner-break flags (vectorised)."""
        deltas = np.diff(chain.times).astype(np.float64)
        deltas = np.maximum(deltas, 1.0)
        distances = np.hypot(np.diff(chain.xs), np.diff(chain.ys))

        breaks = np.zeros(distances.size, dtype=bool)
        spinner_times = chain.spinners
        if spinner_times.size:
            starts = chain.times[:-1]
            ends = chain.times[1:]
            left = np.searchsorted(spinner_times, starts, side="right")
            right = np.searchsorted(spinner_times, ends, side="right")
            breaks = right > left

        return distances, deltas, breaks

    # ------------------------------------------------------------------
    # Strain
    # ------------------------------------------------------------------
    def _strain_series(
        self,
        distances: np.ndarray,
        deltas: np.ndarray,
        breaks: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Accumulate aim/speed strain with exponential decay per movement."""
        count = int(distances.size)
        aim_series = np.zeros(count, dtype=np.float64)
        speed_series = np.zeros(count, dtype=np.float64)

        aim_strain = 0.0
        speed_strain = 0.0
        for position in range(count):
            delta_ms = float(deltas[position])
            aim_strain *= math.exp(-delta_ms / AIM_DECAY_MS)
            speed_strain *= math.exp(-delta_ms / SPEED_DECAY_MS)

            if not breaks[position]:
                aim_strain += float(distances[position]) / delta_ms
                speed_strain += 1.0 / delta_ms

            aim_series[position] = aim_strain
            speed_series[position] = speed_strain

        return aim_series, speed_series

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------
    def _collect_offenders(
        self,
        chain: "_Chain",
        distances: np.ndarray,
        deltas: np.ndarray,
        velocities: np.ndarray,
        breaks: np.ndarray,
    ) -> list[dict[str, Any]]:
        """List every jump above the cursor speed ceiling."""
        over_limit = np.flatnonzero(velocities > self.max_velocity)
        offenders: list[dict[str, Any]] = []
        for node in over_limit:
            pair = int(node)
            offenders.append(
                {
                    "objectIndex": int(chain.indices[pair + 1]),
                    "fromIndex": int(chain.indices[pair]),
                    "timeMs": int(chain.times[pair + 1]),
                    "deltaTimeMs": int(round(float(deltas[pair]))),
                    "distancePx": round(float(distances[pair]), 2),
                    "cursorVelocityPxPerMs": round(float(velocities[pair]), 3),
                }
            )
        return offenders

    def _empty_report(self, object_count: int) -> dict[str, Any]:
        return {
            "playable": True,
            "status": "Playable",
            "predictedStarRating": 0.0,
            "aimStarRating": 0.0,
            "speedStarRating": 0.0,
            "aimPeakStrain": 0.0,
            "speedPeakStrain": 0.0,
            "maxCursorVelocityPxPerMs": 0.0,
            "velocityLimitPxPerMs": round(self.max_velocity, 3),
            "objectCount": object_count,
            "movementCount": 0,
            "unplayableObjects": [],
        }


class _Chain:
    """Flat positional-object arrays plus their indices in the source list."""

    __slots__ = ("times", "xs", "ys", "indices", "spinners")

    def __init__(
        self,
        times: np.ndarray,
        xs: np.ndarray,
        ys: np.ndarray,
        indices: list[int],
        spinners: np.ndarray,
    ) -> None:
        self.times = times
        self.xs = xs
        self.ys = ys
        self.indices = indices
        self.spinners = spinners


def _spinner_times(hit_objects: Sequence[Any]) -> np.ndarray:
    """Times of every spinner in the payload, sorted."""
    times = [
        int(item["time"])
        for item in hit_objects
        if isinstance(item, Mapping)
        and str(item.get("type", "")) == "spinner"
        and isinstance(item.get("time"), (int, float))
    ]
    if not times:
        return np.empty(0, dtype=np.int64)
    return np.asarray(sorted(times), dtype=np.int64)


def _spans_spinner(spinner_times: np.ndarray, start_ms: float, end_ms: int) -> bool:
    """Whether a spinner lies strictly between two positional objects."""
    if not spinner_times.size:
        return False
    left = int(np.searchsorted(spinner_times, start_ms, side="right"))
    right = int(np.searchsorted(spinner_times, end_ms, side="right"))
    return right > left


def _sliding_peak(values: np.ndarray, window: int) -> list[float]:
    """Sliding-window maxima over ``values`` using a monotonic deque (O(N))."""
    if values.size == 0:
        return []
    window = max(1, int(window))
    peaks: list[float] = []
    candidates: deque[int] = deque()

    for position in range(values.size):
        current = float(values[position])
        while candidates and float(values[candidates[-1]]) <= current:
            candidates.pop()
        candidates.append(position)
        if candidates[0] <= position - window:
            candidates.popleft()
        if position >= window - 1:
            peaks.append(float(values[candidates[0]]))

    return peaks


def _weighted_peak_average(peaks: list[float], fraction: float) -> float:
    """Average the strongest ``fraction`` of peaks, weighting the very top most."""
    if not peaks:
        return 0.0
    ordered = sorted(peaks, reverse=True)
    count = max(1, int(round(len(ordered) * max(0.0, fraction))))
    total_weight = 0.0
    accumulated = 0.0
    for rank, value in enumerate(ordered[:count]):
        weight = float(count - rank)
        accumulated += value * weight
        total_weight += weight
    return accumulated / total_weight if total_weight else 0.0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))

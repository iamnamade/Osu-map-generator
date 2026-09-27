from __future__ import annotations

from .common import clamp, mean, normalize
from .loader import LoadedDifficultyMap
from .metrics import compute_pair_diagnostics
from .models import DifficultyCurvePoint


def build_difficulty_curve(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    reading_score: float,
    rhythm_score: float,
    window_ms: int = 4000,
    step_ms: int = 1000,
) -> list[DifficultyCurvePoint]:
    """Build a timeline of difficulty samples over the whole map."""
    objects = beatmap.objects
    if not objects:
        return []

    positioned = [item for item in objects if item.is_positioned]
    first_time = objects[0].time
    last_time = objects[-1].end_time or objects[-1].time
    span = max(window_ms, last_time - first_time)

    points: list[DifficultyCurvePoint] = []
    cursor = first_time
    while cursor < last_time:
        window_start = cursor
        window_end = cursor + window_ms
        points.append(
            _sample_window(
                positioned,
                metrics,
                reading_score,
                rhythm_score,
                window_start,
                window_end,
            )
        )
        cursor += step_ms
        if window_end >= last_time and span <= window_ms * 2:
            break

    # Moving-average smoothing over 3 samples keeps the curve readable.
    smoothed: list[DifficultyCurvePoint] = []
    for index, point in enumerate(points):
        neighbors = [points[max(0, index + offset)] for offset in range(-1, 2) if 0 <= index + offset < len(points)]
        smoothed.append(
            DifficultyCurvePoint(
                time_ms=point.time_ms,
                difficulty_score=_avg_attribute(neighbors, "difficulty_score"),
                density=_avg_attribute(neighbors, "density"),
                speed=_avg_attribute(neighbors, "speed"),
                flow=_avg_attribute(neighbors, "flow"),
                reading=_avg_attribute(neighbors, "reading"),
                rhythm=_avg_attribute(neighbors, "rhythm"),
            )
        )
    return smoothed


def _sample_window(
    positioned,
    metrics,
    reading_score: float,
    rhythm_score: float,
    start_ms: int,
    end_ms: int,
) -> DifficultyCurvePoint:
    in_window = [
        item for item in positioned if start_ms <= item.time < end_ms
    ]
    window_seconds = max(1.0, (end_ms - start_ms) / 1000.0)
    density = len(in_window) / window_seconds

    pairs = compute_pair_diagnostics_between(positioned, start_ms, end_ms)
    velocities = [float(pair["velocityPps"]) for pair in pairs]
    distances = [float(pair["distancePx"]) for pair in pairs]
    speed = mean(velocities) if velocities else 0.0

    # Flow proxy: small jumps with enough time feel smooth.
    flow = 1.0
    if pairs:
        smooth_pairs = [
            pair
            for pair in pairs
            if float(pair["distancePx"]) <= 120.0 and float(pair["timeGapMs"]) >= 250.0
        ]
        flow = len(smooth_pairs) / max(1, len(pairs))

    reading = clamp(reading_score + normalize(density, 3.5) * 0.2, 0.0, 1.0)
    rhythm = clamp(rhythm_score + _window_rhythm_proxy(pairs), 0.0, 1.0)

    difficulty_score = (
        normalize(density, 3.5) * 0.4
        + normalize(speed, 900.0) * 0.3
        + reading * 0.15
        + rhythm * 0.15
    )
    difficulty_score = clamp(difficulty_score, 0.0, 1.0)

    return DifficultyCurvePoint(
        time_ms=start_ms,
        difficulty_score=difficulty_score,
        density=density,
        speed=speed,
        flow=clamp(flow, 0.0, 1.0),
        reading=reading,
        rhythm=rhythm,
    )


def compute_pair_diagnostics_between(positioned, start_ms: int, end_ms: int):
    """Pairs where both endpoints fall inside the window."""
    in_window = [
        item for item in positioned if start_ms <= item.time < end_ms
    ]
    result = []
    for index in range(1, len(in_window)):
        left = in_window[index - 1]
        right = in_window[index]
        distance = (
            ((right.x - left.x) ** 2 + (right.y - left.y) ** 2) ** 0.5  # type: ignore[operator]
        )
        delta_ms = max(1, right.time - left.time)
        result.append(
            {
                "distancePx": distance,
                "timeGapMs": delta_ms,
                "velocityPps": distance / (delta_ms / 1000.0),
            }
        )
    return result


def _window_rhythm_proxy(pairs) -> float:
    if not pairs:
        return 0.0
    gaps = [float(pair["timeGapMs"]) for pair in pairs]
    average = mean(gaps)
    if average <= 0:
        return 0.0
    switches = sum(
        1
        for left, right in zip(gaps, gaps[1:], strict=False)
        if abs(right - left) / average >= 0.4
    )
    return clamp(switches / max(1, len(gaps) - 1), 0.0, 1.0)


def _avg_attribute(points, attribute: str) -> float:
    values = [getattr(point, attribute) for point in points]
    return round(mean(values), 4) if values else 0.0

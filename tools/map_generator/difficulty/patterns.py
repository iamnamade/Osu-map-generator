from __future__ import annotations

import math

from .common import clamp, mean, normalize
from .loader import DifficultyObject, LoadedDifficultyMap
from .models import PatternDifficulty


def score_patterns(beatmap: LoadedDifficultyMap, *, metrics) -> list[PatternDifficulty]:
    """Classify and score patterns independently: streams, bursts,
    cross-screen jumps, triangles, rectangles, slider chains, technical
    patterns, wide jumps, dense clusters."""
    positioned = [item for item in beatmap.objects if item.is_positioned]
    patterns: list[PatternDifficulty] = []

    # Sliding windows of 3-6 consecutive positioned objects.
    for window_size in range(3, 7):
        for start_index in range(len(positioned) - window_size + 1):
            window = positioned[start_index : start_index + window_size]
            classification = _classify_window(window)
            if classification is None:
                continue
            score = _score_window(window, classification, metrics)
            if score < 0.1:
                continue
            patterns.append(
                PatternDifficulty(
                    pattern=classification,
                    start_ms=window[0].time,
                    end_ms=window[-1].time,
                    object_count=len(window),
                    score=score,
                )
            )

    # Single-object wide jumps and cross-screen jumps (pair-based).
    for index in range(1, len(positioned)):
        left = positioned[index - 1]
        right = positioned[index]
        distance = _pair_distance(left, right)
        time_gap = right.time - left.time
        if distance >= 340.0 and time_gap <= 900:
            patterns.append(
                PatternDifficulty(
                    pattern="cross-screen jump",
                    start_ms=left.time,
                    end_ms=right.time,
                    object_count=2,
                    score=_pair_jump_score(distance, time_gap),
                )
            )
        elif distance >= 260.0 and time_gap <= 700:
            patterns.append(
                PatternDifficulty(
                    pattern="wide jump",
                    start_ms=left.time,
                    end_ms=right.time,
                    object_count=2,
                    score=_pair_jump_score(distance, time_gap),
                )
            )

    # Slider chains: 3+ consecutive sliders.
    slider_chain: list[DifficultyObject] = []
    for item in positioned:
        if item.object_type == "slider":
            slider_chain.append(item)
        else:
            if len(slider_chain) >= 3:
                patterns.append(
                    PatternDifficulty(
                        pattern="slider chain",
                        start_ms=slider_chain[0].time,
                        end_ms=slider_chain[-1].end_time or slider_chain[-1].time,
                        object_count=len(slider_chain),
                        score=_slider_chain_score(slider_chain),
                    )
                )
            slider_chain = []
    if len(slider_chain) >= 3:
        patterns.append(
            PatternDifficulty(
                pattern="slider chain",
                start_ms=slider_chain[0].time,
                end_ms=slider_chain[-1].end_time or slider_chain[-1].time,
                object_count=len(slider_chain),
                score=_slider_chain_score(slider_chain),
            )
        )

    # Dense clusters: 5+ objects within 900ms.
    times = [item.time for item in positioned]
    for index in range(len(times) - 4):
        cluster = positioned[index : index + 5]
        span = cluster[-1].time - cluster[0].time
        if span <= 900:
            patterns.append(
                PatternDifficulty(
                    pattern="dense cluster",
                    start_ms=cluster[0].time,
                    end_ms=cluster[-1].time,
                    object_count=5,
                    score=normalize(metrics.objects_per_second, 3.5) * 0.8,
                )
            )

    # Streams and bursts (run-based, full length).
    patterns.extend(_score_stream_runs(positioned, metrics))
    return _deduplicate(patterns)


def _classify_window(window: list[DifficultyObject]) -> str | None:
    """Return the dominant pattern label for a 3-6 object window."""
    distances = [
        _pair_distance(window[index], window[index + 1])
        for index in range(len(window) - 1)
    ]
    time_gaps = [
        window[index + 1].time - window[index].time
        for index in range(len(window) - 1)
    ]
    if not distances:
        return None

    all_rapid = all(gap <= 190 for gap in time_gaps)
    mostly_rapid = mean(time_gaps) <= 230
    all_large = all(distance >= 280 for distance in distances)
    mostly_large = mean(distances) >= 240
    average_distance = mean(distances)

    if all_rapid and len(window) >= 5:
        return "stream"
    if mostly_rapid and len(window) <= 4 and average_distance >= 60:
        return "burst"
    if all_large:
        return "cross-screen jump"
    if average_distance >= 260 and all(gap <= 700 for gap in time_gaps):
        return "wide jump"

    if len(window) == 3 and _is_triangle(window):
        return "triangle"
    if len(window) == 4 and _is_rectangle(window):
        return "rectangle"

    turn_count = _sharp_turn_count(window)
    if turn_count >= 2:
        return "technical pattern"
    return None


def _is_triangle(window: list[DifficultyObject]) -> bool:
    if len(window) < 3:
        return False
    a = _pair_distance(window[0], window[1])
    b = _pair_distance(window[1], window[2])
    c = _pair_distance(window[0], window[2])
    lengths = sorted([a, b, c])
    if lengths[0] <= 10:
        return False
    ratio = lengths[2] / max(1.0, lengths[0])
    return 1.0 <= ratio <= 2.2


def _is_rectangle(window: list[DifficultyObject]) -> bool:
    if len(window) < 4:
        return False
    top = _pair_distance(window[0], window[1])
    right = _pair_distance(window[1], window[2])
    bottom = _pair_distance(window[2], window[3])
    left = _pair_distance(window[3], window[0])
    if min(top, right, bottom, left) <= 10:
        return False
    horizontal_ratio = max(top, bottom) / max(1.0, min(top, bottom))
    vertical_ratio = max(right, left) / max(1.0, min(right, left))
    return horizontal_ratio <= 1.8 and vertical_ratio <= 1.8


def _sharp_turn_count(window: list[DifficultyObject]) -> int:
    count = 0
    for index in range(1, len(window) - 1):
        angle = _turn_angle(window[index - 1], window[index], window[index + 1])
        if angle is not None and angle >= 90:
            count += 1
    return count


def _score_window(
    window: list[DifficultyObject],
    classification: str,
    metrics,
) -> float:
    distances = [
        _pair_distance(window[index], window[index + 1])
        for index in range(len(window) - 1)
    ]
    time_gaps = [
        max(1, window[index + 1].time - window[index].time)
        for index in range(len(window) - 1)
    ]
    velocities = [
        distance / (time_gap / 1000.0)
        for distance, time_gap in zip(distances, time_gaps, strict=False)
    ]
    speed_factor = normalize(mean(velocities) if velocities else 0.0, 900.0)
    distance_factor = normalize(mean(distances) if distances else 0.0, 260.0)
    density_factor = normalize(len(window) / max(1.0, window[-1].time - window[0].time) * 1000.0, 6.0)
    turn_factor = normalize(_sharp_turn_count(window) / max(1, len(window) - 1), 0.7)

    if classification == "stream":
        return clamp(density_factor * 0.5 + speed_factor * 0.5, 0.0, 1.0)
    if classification == "burst":
        return clamp(density_factor * 0.4 + speed_factor * 0.4 + distance_factor * 0.2, 0.0, 1.0)
    if classification in ("cross-screen jump", "wide jump"):
        return clamp(distance_factor * 0.6 + speed_factor * 0.4, 0.0, 1.0)
    if classification in ("triangle", "rectangle"):
        return clamp(distance_factor * 0.4 + speed_factor * 0.3 + turn_factor * 0.3, 0.0, 1.0)
    if classification == "technical pattern":
        return clamp(turn_factor * 0.6 + speed_factor * 0.4, 0.0, 1.0)
    return 0.0


def _score_stream_runs(
    positioned: list[DifficultyObject],
    metrics,
) -> list[PatternDifficulty]:
    """Score stream and burst runs at full length."""
    if not positioned:
        return []
    results: list[PatternDifficulty] = []
    run: list[DifficultyObject] = [positioned[0]]
    for item in positioned[1:]:
        if item.time - run[-1].time <= 190:
            run.append(item)
        else:
            if len(run) >= 5:
                results.append(
                    PatternDifficulty(
                        pattern="stream",
                        start_ms=run[0].time,
                        end_ms=run[-1].time,
                        object_count=len(run),
                        score=normalize(len(run) / 8.0, 1.0) * 0.6
                        + normalize(metrics.objects_per_second, 3.5) * 0.4,
                    )
                )
            elif len(run) in (3, 4):
                results.append(
                    PatternDifficulty(
                        pattern="burst",
                        start_ms=run[0].time,
                        end_ms=run[-1].time,
                        object_count=len(run),
                        score=normalize(len(run) / 4.0, 1.0) * 0.6
                        + normalize(metrics.objects_per_second, 3.5) * 0.4,
                    )
                )
            run = [item]
    if len(run) >= 5:
        results.append(
            PatternDifficulty(
                pattern="stream",
                start_ms=run[0].time,
                end_ms=run[-1].time,
                object_count=len(run),
                score=normalize(len(run) / 8.0, 1.0) * 0.6
                + normalize(metrics.objects_per_second, 3.5) * 0.4,
            )
        )
    elif len(run) in (3, 4):
        results.append(
            PatternDifficulty(
                pattern="burst",
                start_ms=run[0].time,
                end_ms=run[-1].time,
                object_count=len(run),
                score=normalize(len(run) / 4.0, 1.0) * 0.6
                + normalize(metrics.objects_per_second, 3.5) * 0.4,
            )
        )
    return results


def _slider_chain_score(chain: list[DifficultyObject]) -> float:
    lengths = [
        max(1, item.duration_ms)
        for item in chain
        if item.duration_ms > 0
    ]
    length_factor = normalize(mean(lengths) if lengths else 0.0, 500.0)
    return clamp(0.3 + length_factor * 0.5, 0.0, 1.0)


def _pair_jump_score(distance: float, time_gap: int) -> float:
    velocity = distance / max(1.0, time_gap / 1000.0)
    return clamp(
        normalize(distance, 420.0) * 0.5 + normalize(velocity, 1100.0) * 0.5,
        0.0,
        1.0,
    )


def _pair_distance(left: DifficultyObject, right: DifficultyObject) -> float:
    if left.x is None or left.y is None or right.x is None or right.y is None:
        return 0.0
    return math.hypot(right.x - left.x, right.y - left.y)


def _turn_angle(
    left: DifficultyObject,
    middle: DifficultyObject,
    right: DifficultyObject,
) -> float | None:
    if (
        left.x is None
        or left.y is None
        or middle.x is None
        or middle.y is None
        or right.x is None
        or right.y is None
    ):
        return None
    vector_a = (middle.x - left.x, middle.y - left.y)
    vector_b = (right.x - middle.x, right.y - middle.y)
    magnitude_a = math.hypot(*vector_a)
    magnitude_b = math.hypot(*vector_b)
    if magnitude_a <= 0 or magnitude_b <= 0:
        return None
    dot = vector_a[0] * vector_b[0] + vector_a[1] * vector_b[1]
    cosine = clamp(dot / (magnitude_a * magnitude_b), -1.0, 1.0)
    return math.degrees(math.acos(cosine))


def _deduplicate(patterns: list[PatternDifficulty]) -> list[PatternDifficulty]:
    """Remove overlapping duplicates by pattern+startMs, keeping the longest."""
    by_key: dict[tuple[str, int], PatternDifficulty] = {}
    for pattern in patterns:
        key = (pattern.pattern, pattern.start_ms)
        existing = by_key.get(key)
        if existing is None or pattern.object_count > existing.object_count:
            by_key[key] = pattern
    return sorted(by_key.values(), key=lambda item: (item.start_ms, item.pattern))

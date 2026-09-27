from __future__ import annotations

from .common import bucket_count, clamp, mean, normalize
from .loader import LoadedDifficultyMap
from .models import RhythmMetrics


def analyze_rhythm(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    bpm: float | None = None,
) -> RhythmMetrics:
    """Estimate rhythm difficulty: syncopation, subdivision variety, rhythm
    switches, timing consistency, tempo changes, off-beat notes, triplets, bursts."""
    objects = beatmap.objects
    gaps = [
        right.time - left.time
        for left, right in zip(objects, objects[1:], strict=False)
        if right.time > left.time
    ]
    if not gaps:
        return RhythmMetrics(
            syncopation_ratio=0.0,
            subdivision_variety=0.0,
            rhythm_switch_count=0,
            timing_consistency=0.0,
            tempo_change_count=0,
            offbeat_ratio=0.0,
            triplet_count=0,
            burst_count=0,
            score=0.0,
        )

    mean_gap = mean(gaps)
    if mean_gap <= 0:
        mean_gap = 1.0

    # Subdivision variety: how many distinct gap buckets exist.
    subdivision_variety = bucket_count([float(gap) for gap in gaps], max(30.0, mean_gap * 0.25)) / max(1, len(gaps))

    # Rhythm switches: sign changes in the gap delta series.
    rhythm_switch_count = 0
    tempo_change_count = 0
    for left, right in zip(gaps, gaps[1:], strict=False):
        delta = right - left
        if abs(delta) >= mean_gap * 0.4:
            rhythm_switch_count += 1
        if abs(delta) >= mean_gap * 0.6:
            tempo_change_count += 1

    # Timing consistency: stability of the gap series.
    gap_std = _standard_deviation([float(gap) for gap in gaps])
    timing_consistency = clamp(1.0 - gap_std / max(1.0, mean_gap * 0.6), 0.0, 1.0)

    # Syncopation: gaps that are not near the dominant beat subdivision.
    dominant_gap = _dominant_gap(gaps)
    syncopation = [
        gap
        for gap in gaps
        if _gap_error_ratio(gap, dominant_gap) > 0.25
    ]
    syncopation_ratio = len(syncopation) / max(1, len(gaps)) if gaps else 0.0

    # Off-beat ratio: objects placed at an odd fraction of the beat.
    offbeat_ratio = syncopation_ratio

    # Triplets: three consecutive near-equal small gaps.
    triplet_count = 0
    burst_count = 0
    rapid_threshold = max(140.0, mean_gap * 0.5)
    for index in range(len(gaps) - 2):
        triple = gaps[index : index + 3]
        if max(triple) - min(triple) <= mean_gap * 0.12 and all(gap <= rapid_threshold for gap in triple):
            triplet_count += 1
    burst_run = 0
    for gap in gaps:
        if gap <= rapid_threshold:
            burst_run += 1
        else:
            if burst_run >= 3:
                burst_count += 1
            burst_run = 0
    if burst_run >= 3:
        burst_count += 1

    rhythm_score = (
        syncopation_ratio * 0.25
        + normalize(subdivision_variety, 0.5) * 0.2
        + normalize(rhythm_switch_count / max(1, len(gaps)), 0.5) * 0.2
        + (1.0 - timing_consistency) * 0.15
        + normalize(triplet_count / max(1, len(gaps)), 0.15) * 0.1
        + normalize(burst_count / max(1, len(gaps)), 0.12) * 0.1
    )
    rhythm_score = clamp(rhythm_score, 0.0, 1.0)

    return RhythmMetrics(
        syncopation_ratio=round(syncopation_ratio, 4),
        subdivision_variety=round(subdivision_variety, 4),
        rhythm_switch_count=rhythm_switch_count,
        timing_consistency=round(timing_consistency, 4),
        tempo_change_count=tempo_change_count,
        offbeat_ratio=round(offbeat_ratio, 4),
        triplet_count=triplet_count,
        burst_count=burst_count,
        score=rhythm_score,
    )


def _standard_deviation(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return variance**0.5


def _dominant_gap(gaps: list[int]) -> float:
    """Return the most common gap rounded to 10ms buckets."""
    if not gaps:
        return 1.0
    buckets: dict[int, int] = {}
    for gap in gaps:
        bucket = int(gap // 10)
        buckets[bucket] = buckets.get(bucket, 0) + 1
    dominant = max(buckets.items(), key=lambda item: item[1])[0]
    return float(dominant * 10 + 5)


def _gap_error_ratio(gap: int, reference: float) -> float:
    if reference <= 0:
        return 1.0
    nearest_multiple = round(gap / reference)
    nearest = max(1, nearest_multiple) * reference
    return abs(gap - nearest) / max(1.0, reference)

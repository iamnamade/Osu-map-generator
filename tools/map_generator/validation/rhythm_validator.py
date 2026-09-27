from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from statistics import median, pstdev

from ..config import DifficultyPreset
from ..models import AudioAnalysis
from .models import ParsedBeatmap, RhythmMetrics, ValidationIssue

GAP_QUANTIZATION_MS = 10


@dataclass(frozen=True)
class RhythmValidationResult:
    metrics: RhythmMetrics
    issues: list[ValidationIssue]
    gaps_ms: list[int]


def validate_rhythm(
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
) -> RhythmValidationResult:
    issues: list[ValidationIssue] = []
    gaps = [
        right.time - left.time
        for left, right in zip(beatmap.objects, beatmap.objects[1:], strict=False)
    ]

    if not gaps:
        return RhythmValidationResult(
            metrics=RhythmMetrics(
                min_gap_ms=analysis.duration_ms,
                max_gap_ms=analysis.duration_ms,
                average_gap_ms=float(analysis.duration_ms),
                median_gap_ms=float(analysis.duration_ms),
                gap_standard_deviation_ms=0.0,
                gap_percentiles_ms={"p10": float(analysis.duration_ms), "p25": float(analysis.duration_ms), "p75": float(analysis.duration_ms), "p90": float(analysis.duration_ms)},
                rapid_sequence_count=0,
                long_empty_space_count=0,
                repeated_equal_gap_runs=0,
                common_rhythm_intervals_ms=[],
            ),
            issues=issues,
            gaps_ms=[],
        )

    rapid_sequence_count = 0
    long_empty_space_count = 0
    repeated_equal_gap_runs = 0
    minimum_dense_gap = int(round(preset.min_gap_ms * 1.15))
    long_gap_threshold = max(int(round(preset.target_gap_ms * 2.35)), 1400)
    dominant_counter: Counter[int] = Counter()

    dense_run_start: int | None = None
    equal_gap_run = 1

    for index, gap in enumerate(gaps):
        dominant_counter[_quantize_gap(gap)] += 1

        if gap < preset.min_gap_ms:
            issues.append(
                ValidationIssue(
                    code="RHYTHM_GAP_BELOW_MINIMUM",
                    severity="error",
                    message="Consecutive objects are closer together than the configured minimum gap.",
                    category="rhythm",
                    object_ids=[beatmap.objects[index].id, beatmap.objects[index + 1].id],
                    start_time_ms=beatmap.objects[index].time,
                    end_time_ms=beatmap.objects[index + 1].time,
                    measured_value=float(gap),
                    allowed_value=float(preset.min_gap_ms),
                    suggestion="Remove or delay one of the objects in this burst.",
                )
            )

        if gap <= minimum_dense_gap:
            dense_run_start = index if dense_run_start is None else dense_run_start
        elif dense_run_start is not None:
            run_length = index - dense_run_start
            if run_length >= 2:
                rapid_sequence_count += 1
                issues.append(
                    ValidationIssue(
                        code="RHYTHM_DENSE_RUN",
                        severity="warning",
                        message="Several near-minimum gaps appear back to back.",
                        category="rhythm",
                        object_ids=[beatmap.objects[dense_run_start].id, beatmap.objects[index].id],
                        start_time_ms=beatmap.objects[dense_run_start].time,
                        end_time_ms=beatmap.objects[index].time,
                        measured_value=float(run_length + 1),
                        allowed_value=2.0,
                        suggestion="Break the sequence up with a slightly larger rhythmic gap.",
                    )
                )
            dense_run_start = None

        if gap >= long_gap_threshold:
            long_empty_space_count += 1
            midpoint = beatmap.objects[index].time + gap // 2
            if _gap_overlaps_high_energy(analysis, beatmap.objects[index].time, beatmap.objects[index + 1].time):
                issues.append(
                    ValidationIssue(
                        code="RHYTHM_LONG_HIGH_ENERGY_GAP",
                        severity="warning",
                        message="A long empty gap spans a section with strong audio energy.",
                        category="rhythm",
                        object_ids=[beatmap.objects[index].id, beatmap.objects[index + 1].id],
                        start_time_ms=beatmap.objects[index].time,
                        end_time_ms=beatmap.objects[index + 1].time,
                        measured_value=float(gap),
                        allowed_value=float(long_gap_threshold),
                        suggestion="Consider representing more of the musical activity in this window.",
                    )
                )
            elif analysis.energy_at(midpoint) > preset.high_energy_threshold:
                issues.append(
                    ValidationIssue(
                        code="RHYTHM_LONG_GAP_DURING_ACTIVE_AUDIO",
                        severity="info",
                        message="This gap is longer than expected for the surrounding activity.",
                        category="rhythm",
                        object_ids=[beatmap.objects[index].id, beatmap.objects[index + 1].id],
                        start_time_ms=beatmap.objects[index].time,
                        end_time_ms=beatmap.objects[index + 1].time,
                        measured_value=float(gap),
                        allowed_value=float(long_gap_threshold),
                    )
                )

        if gap < int(round(preset.target_gap_ms * 0.68)):
            midpoint = beatmap.objects[index].time + gap // 2
            if analysis.energy_at(midpoint) < preset.quiet_energy_threshold * 1.1:
                issues.append(
                    ValidationIssue(
                        code="RHYTHM_DENSE_QUIET_CLUSTER",
                        severity="warning",
                        message="Dense object timing appears in a relatively quiet section.",
                        category="rhythm",
                        object_ids=[beatmap.objects[index].id, beatmap.objects[index + 1].id],
                        start_time_ms=beatmap.objects[index].time,
                        end_time_ms=beatmap.objects[index + 1].time,
                        measured_value=float(gap),
                        allowed_value=float(preset.target_gap_ms * 0.68),
                        suggestion="Thin this cluster or reserve it for stronger musical moments.",
                    )
                )

        if index > 0 and index < len(gaps) - 1:
            previous_gap = gaps[index - 1]
            next_gap = gaps[index + 1]
            if gap < min(previous_gap, next_gap) * 0.6:
                issues.append(
                    ValidationIssue(
                        code="RHYTHM_ISOLATED_SPEED_SPIKE",
                        severity="warning",
                        message="A single isolated gap is much faster than its neighbors.",
                        category="rhythm",
                        object_ids=[beatmap.objects[index].id, beatmap.objects[index + 1].id],
                        start_time_ms=beatmap.objects[index].time,
                        end_time_ms=beatmap.objects[index + 1].time,
                        measured_value=float(gap),
                        allowed_value=float(min(previous_gap, next_gap) * 0.6),
                        suggestion="Smooth the transition into and out of this spike.",
                    )
                )

        if index > 0 and _quantize_gap(gap) == _quantize_gap(gaps[index - 1]):
            equal_gap_run += 1
        else:
            if equal_gap_run >= 3:
                repeated_equal_gap_runs += 1
            equal_gap_run = 1

    if dense_run_start is not None:
        run_length = len(gaps) - dense_run_start
        if run_length >= 2:
            rapid_sequence_count += 1

    if equal_gap_run >= 3:
        repeated_equal_gap_runs += 1

    gap_standard_deviation_ms = pstdev(gaps) if len(gaps) > 1 else 0.0
    percentiles = _build_percentiles(gaps)
    common_rhythm_intervals = _select_common_intervals(dominant_counter)

    if (
        len(gaps) >= 8
        and gap_standard_deviation_ms < max(18, preset.target_gap_ms * 0.12)
        and dominant_counter
        and dominant_counter.most_common(1)[0][1] / len(gaps) >= 0.6
    ):
        issues.append(
            ValidationIssue(
                code="RHYTHM_MECHANICAL_UNIFORMITY",
                severity="warning",
                message="Gap timing is unusually uniform across a long section.",
                category="rhythm",
                measured_value=gap_standard_deviation_ms,
                allowed_value=float(max(18, preset.target_gap_ms * 0.12)),
                suggestion="Add more rhythmic variation unless the music strongly supports a metronomic pattern.",
            )
        )

    metrics = RhythmMetrics(
        min_gap_ms=min(gaps),
        max_gap_ms=max(gaps),
        average_gap_ms=sum(gaps) / len(gaps),
        median_gap_ms=float(median(gaps)),
        gap_standard_deviation_ms=gap_standard_deviation_ms,
        gap_percentiles_ms=percentiles,
        rapid_sequence_count=rapid_sequence_count,
        long_empty_space_count=long_empty_space_count,
        repeated_equal_gap_runs=repeated_equal_gap_runs,
        common_rhythm_intervals_ms=common_rhythm_intervals,
    )

    return RhythmValidationResult(metrics=metrics, issues=issues, gaps_ms=gaps)


def _quantize_gap(gap_ms: int) -> int:
    return int(round(gap_ms / GAP_QUANTIZATION_MS) * GAP_QUANTIZATION_MS)


def _build_percentiles(values: list[int]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "p10": _percentile(ordered, 0.10),
        "p25": _percentile(ordered, 0.25),
        "p75": _percentile(ordered, 0.75),
        "p90": _percentile(ordered, 0.90),
    }


def _percentile(values: list[int], ratio: float) -> float:
    if not values:
        return 0.0

    index = (len(values) - 1) * ratio
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    weight = index - lower
    return values[lower] * (1 - weight) + values[upper] * weight


def _select_common_intervals(counter: Counter[int]) -> list[int]:
    ranked = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [interval for interval, _count in ranked[:5]]


def _gap_overlaps_high_energy(analysis: AudioAnalysis, start_ms: int, end_ms: int) -> bool:
    return any(
        region.start_ms <= end_ms and region.end_ms >= start_ms
        for region in analysis.high_energy_regions
    )

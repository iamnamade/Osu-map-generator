from __future__ import annotations

from .common import clamp, longest_run, mean, normalize
from .loader import LoadedDifficultyMap
from .models import StaminaMetrics


def analyze_stamina(
    beatmap: LoadedDifficultyMap,
    *,
    metrics,
    high_density_gap_ms: float = 320.0,
    rest_gap_ms: float = 900.0,
) -> StaminaMetrics:
    """Estimate endurance demand: continuous activity, high density, stream
    duration, rest frequency, and slider workload."""
    positioned_times = [
        item.time for item in beatmap.objects if item.is_positioned
    ]
    if len(positioned_times) < 2:
        return StaminaMetrics(
            continuous_activity_ms=0,
            high_density_duration_ms=0,
            stream_duration_ms=0,
            rest_frequency=0.0,
            slider_workload=0.0,
            score=0.0,
        )

    gaps = [
        right - left
        for left, right in zip(positioned_times, positioned_times[1:], strict=False)
        if right > left
    ]
    active_duration_ms = max(1, positioned_times[-1] - positioned_times[0])

    # Continuous activity: longest run of positioned objects with no rest.
    activity_flags = [gap < rest_gap_ms for gap in gaps]
    longest_activity_run = longest_run(activity_flags)
    continuous_activity_ms = 0
    if longest_activity_run > 0:
        # Approximate by summing the gap durations inside the longest run.
        run_sum = 0
        current = 0
        best = 0
        for gap, is_active in zip(gaps, activity_flags, strict=False):
            if is_active:
                current += gap
                best = max(best, current)
            else:
                current = 0
        continuous_activity_ms = best

    # High density duration: total ms where gaps stay under the density gap.
    high_density_duration_ms = sum(
        gap for gap in gaps if gap <= high_density_gap_ms
    )

    # Stream duration: time spent in runs of rapid gaps.
    stream_duration_ms = sum(
        gap for gap in gaps if gap <= 190.0
    )

    # Rest frequency: number of rest gaps per minute.
    rest_count = sum(1 for gap in gaps if gap >= rest_gap_ms)
    minutes = active_duration_ms / 60000.0
    rest_frequency = rest_count / max(1e-6, minutes)

    # Slider workload: fraction of active time spent inside slider bodies.
    slider_duration_ms = sum(
        item.duration_ms for item in beatmap.objects if item.object_type == "slider"
    )
    slider_workload = clamp(slider_duration_ms / max(1, active_duration_ms), 0.0, 1.0)

    activity_ratio = clamp(continuous_activity_ms / max(1, active_duration_ms), 0.0, 1.0)
    high_density_ratio = clamp(high_density_duration_ms / max(1, active_duration_ms), 0.0, 1.0)

    stamina_score = (
        normalize(activity_ratio, 0.55) * 0.4
        + normalize(high_density_ratio, 0.4) * 0.3
        + normalize(rest_frequency / 30.0, 1.0) * 0.1
        + slider_workload * 0.1
        + normalize(metrics.longest_stream_length / 8.0, 1.0) * 0.1
    )
    stamina_score = clamp(stamina_score, 0.0, 1.0)

    return StaminaMetrics(
        continuous_activity_ms=continuous_activity_ms,
        high_density_duration_ms=high_density_duration_ms,
        stream_duration_ms=stream_duration_ms,
        rest_frequency=round(rest_frequency, 4),
        slider_workload=round(slider_workload, 4),
        score=stamina_score,
    )

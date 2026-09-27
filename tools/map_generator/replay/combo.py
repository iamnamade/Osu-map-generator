from __future__ import annotations

from ..difficulty.common import mean
from .models import ComboStats, HitEvent

_STREAM_GAP_MS = 220.0
_CLUSTER_WINDOW_MS = 600.0


def simulate_combo(events: list[HitEvent]) -> ComboStats:
    """Estimate combo evolution from one deterministic simulated run.

    Tracks combo breaks, the longest combo, recovery time after mistakes,
    miss clusters, isolated misses, and stream failures.
    """
    total = max(1, len(events))
    combo = 0
    max_combo = 0
    combo_breaks = 0
    break_combos: list[int] = []
    miss_times: list[int] = []
    recovery_sum = 0.0
    recovery_count = 0

    for index, event in enumerate(events):
        if event.result == "miss":
            combo_breaks += 1
            break_combos.append(combo)
            miss_times.append(event.time_ms)
            for next_index in range(index + 1, len(events)):
                if events[next_index].result != "miss":
                    recovery_sum += events[next_index].time_ms - event.time_ms
                    recovery_count += 1
                    break
            combo = 0
        else:
            combo += 1
            max_combo = max(max_combo, combo)

    clusters = _count_clusters(miss_times)
    isolated = _count_isolated(miss_times)
    stream_failures = _count_stream_failures(events, miss_times)
    recovery_time = recovery_sum / recovery_count if recovery_count else 0.0
    average_break_combo = mean(break_combos) if break_combos else float(max_combo)

    return ComboStats(
        combo_breaks=combo_breaks,
        max_combo=max_combo,
        expected_combo_pct=round(max_combo / total, 4),
        recovery_time_ms=round(recovery_time, 2),
        miss_clusters=clusters,
        isolated_misses=isolated,
        stream_failures=stream_failures,
        average_combo_before_break=round(average_break_combo, 2),
    )


def _count_clusters(miss_times: list[int]) -> int:
    """Count connected groups of misses within the cluster window.

    Two consecutive misses (in time order) belong to the same cluster when
    the gap between them is within the cluster window, so chains of misses
    form a single cluster.
    """
    if not miss_times:
        return 0
    ordered = sorted(miss_times)
    clusters = 1
    for left, right in zip(ordered, ordered[1:], strict=False):
        if right - left > _CLUSTER_WINDOW_MS:
            clusters += 1
    return clusters


def _count_isolated(miss_times: list[int]) -> int:
    """Count misses that have no other miss within the cluster window."""
    if not miss_times:
        return 0
    ordered = sorted(miss_times)
    isolated = 0
    for index, current in enumerate(ordered):
        near_previous = index > 0 and current - ordered[index - 1] <= _CLUSTER_WINDOW_MS
        near_next = (
            index + 1 < len(ordered)
            and ordered[index + 1] - current <= _CLUSTER_WINDOW_MS
        )
        if not near_previous and not near_next:
            isolated += 1
    return isolated


def _count_stream_failures(events: list[HitEvent], miss_times: list[int]) -> int:
    """Count misses that fall inside dense stream-like passages."""
    if not miss_times:
        return 0
    failure_times = set(miss_times)
    failures = 0
    for index, event in enumerate(events):
        if event.time_ms not in failure_times:
            continue
        if _dense_run_around(events, index):
            failures += 1
    return failures


def _dense_run_around(events: list[HitEvent], index: int) -> bool:
    left = max(0, index - 3)
    right = min(len(events) - 1, index + 3)
    window = events[left : right + 1]
    dense_pairs = 0
    for current, following in zip(window, window[1:], strict=False):
        if (
            following.time_ms - current.time_ms < _STREAM_GAP_MS
            and current.result != "miss"
            and following.result != "miss"
        ):
            dense_pairs += 1
    return dense_pairs >= 3

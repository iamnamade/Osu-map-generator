from __future__ import annotations

import math
from typing import Iterable, Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def standard_deviation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    variance = sum((value - average) ** 2 for value in values) / len(values)
    return math.sqrt(variance)


def coefficient_of_variation(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = mean(values)
    if average == 0:
        return 0.0
    return standard_deviation(values) / abs(average)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def normalize(value: float, reference: float) -> float:
    return clamp(value / reference if reference > 0 else 0.0, 0.0, 1.0)


def weighted_average(values: Iterable[tuple[float, float]]) -> float:
    """Weighted average of (value, weight) pairs."""
    total_weight = 0.0
    total_value = 0.0
    for value, weight in values:
        if weight <= 0:
            continue
        total_weight += weight
        total_value += value * weight
    return total_value / total_weight if total_weight > 0 else 0.0


def to_score(value: float) -> float:
    """Map a 0..1 value into a 0..10 difficulty score with slight spread."""
    return clamp(value * 10.0, 0.0, 10.0)


def bucket_count(values: Sequence[float], bucket_size: float) -> int:
    buckets: set[int] = set()
    for value in values:
        buckets.add(int(value // bucket_size))
    return len(buckets)


def longest_run(values: Sequence[bool]) -> int:
    longest = 0
    current = 0
    for is_active in values:
        if is_active:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest

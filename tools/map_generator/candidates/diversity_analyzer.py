from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .candidate_config import DiversitySettings
from .candidate_models import CandidateDiversity, CandidateSummary, DiversitySummary, PairwiseSimilarity

PLAYFIELD_DIAGONAL = math.hypot(512, 384)


@dataclass
class DiversityAnalysisResult:
    candidate_diversity: dict[int, CandidateDiversity]
    pairwise_similarities: list[PairwiseSimilarity]
    summary: DiversitySummary


def analyze_diversity(
    *,
    candidates: list[CandidateSummary],
    improved_maps_by_index: dict[int, dict[str, Any]],
    eligible_count: int,
    timing_variation_enabled: bool,
    settings: DiversitySettings,
) -> DiversityAnalysisResult:
    pairwise: list[PairwiseSimilarity] = []
    diversity_values_by_candidate: dict[int, list[float]] = {
        summary.candidate.index: [] for summary in candidates
    }
    near_duplicate_counts: Counter[int] = Counter()

    for left_offset, left_summary in enumerate(candidates):
        left_map = improved_maps_by_index[left_summary.candidate.index]
        for right_summary in candidates[left_offset + 1 :]:
            right_map = improved_maps_by_index[right_summary.candidate.index]
            pair = _compare_maps(
                left_index=left_summary.candidate.index,
                right_index=right_summary.candidate.index,
                left_map=left_map,
                right_map=right_map,
                timing_variation_enabled=timing_variation_enabled,
                settings=settings,
            )
            pairwise.append(pair)
            diversity_values_by_candidate[left_summary.candidate.index].append(pair.diversity_percent)
            diversity_values_by_candidate[right_summary.candidate.index].append(pair.diversity_percent)
            if pair.near_duplicate:
                near_duplicate_counts[left_summary.candidate.index] += 1
                near_duplicate_counts[right_summary.candidate.index] += 1

    groups = _build_duplicate_groups(pairwise)
    candidate_diversity: dict[int, CandidateDiversity] = {}
    for summary in candidates:
        candidate_index = summary.candidate.index
        candidate_values = diversity_values_by_candidate[candidate_index]
        average_diversity = sum(candidate_values) / len(candidate_values) if candidate_values else 100.0
        nearest_neighbor_diversity = min(candidate_values) if candidate_values else 100.0
        similarity_penalty = max(0.0, near_duplicate_counts[candidate_index] * 2.5 - nearest_neighbor_diversity * 0.02)
        candidate_diversity[candidate_index] = CandidateDiversity(
            average_pairwise_diversity=average_diversity,
            nearest_neighbor_diversity=nearest_neighbor_diversity,
            similarity_penalty=min(10.0, similarity_penalty),
            near_duplicate_count=near_duplicate_counts[candidate_index],
        )

    all_diversities = [pair.diversity_percent for pair in pairwise]
    most_unique_candidate = _arg_extreme(candidate_diversity, key=lambda item: item.average_pairwise_diversity, reverse=True)
    most_duplicated_candidate = _arg_extreme(candidate_diversity, key=lambda item: item.near_duplicate_count, reverse=True)
    summary = DiversitySummary(
        candidate_count=len(candidates),
        eligible_count=eligible_count,
        unique_candidate_count=len(candidates) - sum(len(group) - 1 for group in groups),
        near_duplicate_groups=groups,
        average_pairwise_diversity=(sum(all_diversities) / len(all_diversities)) if all_diversities else 100.0,
        minimum_pairwise_diversity=min(all_diversities) if all_diversities else 100.0,
        maximum_pairwise_diversity=max(all_diversities) if all_diversities else 100.0,
        most_unique_candidate=most_unique_candidate,
        most_duplicated_candidate=most_duplicated_candidate,
        pair_count=len(pairwise),
    )
    return DiversityAnalysisResult(
        candidate_diversity=candidate_diversity,
        pairwise_similarities=pairwise,
        summary=summary,
    )


def _compare_maps(
    *,
    left_index: int,
    right_index: int,
    left_map: dict[str, Any],
    right_map: dict[str, Any],
    timing_variation_enabled: bool,
    settings: DiversitySettings,
) -> PairwiseSimilarity:
    left_objects = _objects(left_map)
    right_objects = _objects(right_map)
    coordinate_difference = _coordinate_difference(left_objects, right_objects)
    jump_distance_difference = _histogram_difference(
        _jump_histogram(left_objects),
        _jump_histogram(right_objects),
    )
    region_difference = _histogram_difference(
        _region_histogram(left_objects),
        _region_histogram(right_objects),
    )
    angle_difference = _histogram_difference(
        _angle_histogram(left_objects),
        _angle_histogram(right_objects),
    )
    timing_difference = (
        _timing_difference(left_objects, right_objects) if timing_variation_enabled else 0.0
    )

    weights = [
        (settings.coordinate_weight, 1.0 - min(1.0, coordinate_difference / PLAYFIELD_DIAGONAL)),
        (settings.jump_weight, 1.0 - jump_distance_difference),
        (settings.region_weight, 1.0 - region_difference),
        (settings.angle_weight, 1.0 - angle_difference),
    ]
    if timing_variation_enabled:
        weights.append((settings.timing_weight, 1.0 - min(1.0, timing_difference / 150.0)))

    total_weight = sum(weight for weight, _ in weights) or 1.0
    normalized_similarity = sum(weight * max(0.0, value) for weight, value in weights) / total_weight
    similarity_percent = max(0.0, min(100.0, normalized_similarity * 100.0))
    diversity_percent = max(0.0, 100.0 - similarity_percent)

    return PairwiseSimilarity(
        left_index=left_index,
        right_index=right_index,
        similarity_percent=similarity_percent,
        diversity_percent=diversity_percent,
        coordinate_difference=coordinate_difference,
        jump_distance_difference=jump_distance_difference,
        region_difference=region_difference,
        angle_difference=angle_difference,
        timing_difference=timing_difference,
        near_duplicate=similarity_percent >= settings.near_duplicate_similarity_threshold,
    )


def _objects(map_data: dict[str, Any]) -> list[dict[str, Any]]:
    raw_objects = map_data.get("objects", [])
    return [
        item
        for item in raw_objects
        if isinstance(item, dict) and "x" in item and "y" in item
    ]


def _coordinate_difference(left_objects: list[dict[str, Any]], right_objects: list[dict[str, Any]]) -> float:
    if not left_objects or not right_objects:
        return PLAYFIELD_DIAGONAL

    pair_count = min(len(left_objects), len(right_objects))
    distances = [
        math.hypot(
            float(left_objects[index]["x"]) - float(right_objects[index]["x"]),
            float(left_objects[index]["y"]) - float(right_objects[index]["y"]),
        )
        for index in range(pair_count)
    ]
    missing_penalty = abs(len(left_objects) - len(right_objects)) * (PLAYFIELD_DIAGONAL * 0.15)
    return (sum(distances) / pair_count) + missing_penalty


def _timing_difference(left_objects: list[dict[str, Any]], right_objects: list[dict[str, Any]]) -> float:
    if not left_objects or not right_objects:
        return 150.0

    pair_count = min(len(left_objects), len(right_objects))
    differences = [
        abs(int(left_objects[index]["time"]) - int(right_objects[index]["time"]))
        for index in range(pair_count)
    ]
    return sum(differences) / pair_count


def _jump_histogram(objects: list[dict[str, Any]]) -> list[float]:
    if len(objects) < 2:
        return [1.0, 0.0, 0.0, 0.0, 0.0]
    bins = [0, 0, 0, 0, 0]
    for left, right in zip(objects, objects[1:], strict=False):
        distance = math.hypot(float(right["x"]) - float(left["x"]), float(right["y"]) - float(left["y"]))
        index = min(4, int(distance / 64))
        bins[index] += 1
    total = sum(bins) or 1
    return [value / total for value in bins]


def _region_histogram(objects: list[dict[str, Any]]) -> list[float]:
    bins = [0] * 12
    for item in objects:
        column = min(3, max(0, int(float(item["x"]) / 128)))
        row = min(2, max(0, int(float(item["y"]) / 128)))
        bins[row * 4 + column] += 1
    total = sum(bins) or 1
    return [value / total for value in bins]


def _angle_histogram(objects: list[dict[str, Any]]) -> list[float]:
    if len(objects) < 3:
        return [1.0, 0.0, 0.0, 0.0]
    bins = [0, 0, 0, 0]
    for first, second, third in zip(objects, objects[1:], objects[2:], strict=False):
        left_angle = math.atan2(float(second["y"]) - float(first["y"]), float(second["x"]) - float(first["x"]))
        right_angle = math.atan2(float(third["y"]) - float(second["y"]), float(third["x"]) - float(second["x"]))
        delta = abs((right_angle - left_angle + math.pi) % (2 * math.pi) - math.pi)
        index = min(3, int(delta / (math.pi / 4)))
        bins[index] += 1
    total = sum(bins) or 1
    return [value / total for value in bins]


def _histogram_difference(left_histogram: list[float], right_histogram: list[float]) -> float:
    return sum(abs(left - right) for left, right in zip(left_histogram, right_histogram, strict=False)) / 2.0


def _build_duplicate_groups(pairwise: list[PairwiseSimilarity]) -> list[list[int]]:
    parents: dict[int, int] = {}

    def find(node: int) -> int:
        parents.setdefault(node, node)
        if parents[node] != node:
            parents[node] = find(parents[node])
        return parents[node]

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    for pair in pairwise:
        if pair.near_duplicate:
            union(pair.left_index, pair.right_index)

    groups: dict[int, set[int]] = {}
    for pair in pairwise:
        if not pair.near_duplicate:
            continue
        root = find(pair.left_index)
        groups.setdefault(root, set()).update({pair.left_index, pair.right_index})

    return [sorted(group) for group in sorted(groups.values(), key=lambda item: (len(item), tuple(sorted(item))), reverse=True)]


def _arg_extreme(
    candidates: dict[int, CandidateDiversity],
    *,
    key,
    reverse: bool,
) -> int | None:
    if not candidates:
        return None
    ordered = sorted(
        candidates.items(),
        key=lambda item: (
            key(item[1]),
            -item[0] if reverse else item[0],
        ),
        reverse=reverse,
    )
    return ordered[0][0]

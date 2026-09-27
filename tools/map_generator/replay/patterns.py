from __future__ import annotations

import math
from collections import Counter

from ..difficulty.common import clamp, mean
from ..difficulty.loader import LoadedDifficultyMap
from .models import (
    PatternRecognitionResult,
    PatternRecognizability,
    PatternTransition,
    ReplayPlayerProfile,
)

_BASE_RECOGNIZABILITY: dict[str, float] = {
    "stack": 0.95,
    "linear": 0.85,
    "stream": 0.8,
    "symmetrical": 0.75,
    "burst": 0.65,
    "flow": 0.62,
    "jump": 0.6,
    "zigzag": 0.5,
    "cross-screen": 0.35,
}

_LABELS: dict[str, str] = {
    "stack": "Stack",
    "linear": "Linear",
    "stream": "Stream",
    "symmetrical": "Symmetrical",
    "burst": "Burst",
    "flow": "Flow",
    "jump": "Jump",
    "zigzag": "Zigzag",
    "cross-screen": "Cross-screen jump",
}

_WINDOW_SIZE = 4
_STREAM_GAP_MS = 180.0
_STREAM_JUMP_PX = 70.0
_BURST_GAP_MS = 210.0
_JUMP_DISTANCE_PX = 150.0
_CROSS_SCREEN_PX = 300.0
_STACK_RADIUS_PX = 12.0
_LINEAR_TOLERANCE_DEG = 18.0
_SYMMETRY_TOLERANCE_PX = 6.0
_CONFUSING_TURN_DEG = 100.0


def recognize_patterns(
    beatmap: LoadedDifficultyMap,
    player: ReplayPlayerProfile,
) -> PatternRecognitionResult:
    """Evaluate how recognizable each pattern in the map is.

    Sliding windows are classified into pattern kinds (streams, bursts, jumps,
    stacks, linear, symmetrical, cross-screen jumps, zigzag). Readable patterns
    are rewarded; abrupt pattern switches with sharp angles are penalized as
    confusing transitions.
    """
    positioned = [item for item in beatmap.objects if item.is_positioned]
    if len(positioned) < _WINDOW_SIZE:
        return PatternRecognitionResult(
            patterns=[],
            transitions=[],
            overall_recognizability=1.0,
            transition_penalty=0.0,
            hardest_pattern="none",
        )

    windows: list[tuple[int, int, str]] = []
    for start in range(len(positioned) - _WINDOW_SIZE + 1):
        window = positioned[start : start + _WINDOW_SIZE]
        kind = _classify_window(window)
        windows.append((window[0].time, window[-1].time, kind))

    counts = Counter(kind for _, _, kind in windows)
    memory_boost = player.pattern_memory * 0.08
    patterns = [
        PatternRecognizability(
            kind=kind,
            label=_LABELS.get(kind, kind),
            count=count,
            recognizability=round(
                clamp(_BASE_RECOGNIZABILITY.get(kind, 0.6) + memory_boost, 0.0, 1.0),
                4,
            ),
        )
        for kind, count in sorted(counts.items(), key=lambda item: -item[1])
    ]

    transitions = _build_transitions(positioned, windows)

    per_window = [
        _BASE_RECOGNIZABILITY.get(kind, 0.6) + memory_boost for _, _, kind in windows
    ]
    overall = clamp(mean([clamp(value, 0.0, 1.0) for value in per_window]), 0.0, 1.0)
    transition_penalty = (
        clamp(
            sum(transition.penalty for transition in transitions) / len(transitions),
            0.0,
            1.0,
        )
        if transitions
        else 0.0
    )

    hardest = "flow"
    hardest_value = 1.0
    for _, _, kind in windows:
        recognizability = clamp(
            _BASE_RECOGNIZABILITY.get(kind, 0.6) + memory_boost,
            0.0,
            1.0,
        )
        if recognizability < hardest_value:
            hardest_value = recognizability
            hardest = kind

    return PatternRecognitionResult(
        patterns=patterns,
        transitions=transitions,
        overall_recognizability=round(overall, 4),
        transition_penalty=round(transition_penalty, 4),
        hardest_pattern=hardest,
    )


def _classify_window(window) -> str:
    distances = [
        math.hypot(
            float(right.x) - float(left.x),
            float(right.y) - float(left.y),
        )
        for left, right in zip(window, window[1:], strict=False)
    ]
    gaps = [
        right.time - left.time
        for left, right in zip(window, window[1:], strict=False)
    ]
    average_gap = mean([float(gap) for gap in gaps])
    average_distance = mean(distances)
    maximum_distance = max(distances) if distances else 0.0

    if all(distance < _STACK_RADIUS_PX for distance in distances):
        return "stack"
    if average_gap < _STREAM_GAP_MS and average_distance < _STREAM_JUMP_PX:
        return "stream"
    if maximum_distance > _CROSS_SCREEN_PX:
        return "cross-screen"
    if _is_symmetrical(window, distances):
        return "symmetrical"
    if average_distance > _JUMP_DISTANCE_PX:
        return "jump"
    if average_gap < _BURST_GAP_MS:
        return "burst"
    if _is_linear(window):
        return "linear"
    if _is_zigzag(window):
        return "zigzag"
    return "flow"


def _is_symmetrical(window, distances: list[float]) -> bool:
    if len(window) != 4:
        return False
    center_x = mean([float(item.x) for item in window])
    center_y = mean([float(item.y) for item in window])
    radius = mean(distances) if distances else 0.0
    if radius <= 1e-6:
        return False
    for left, right in ((window[0], window[3]), (window[1], window[2])):
        left_distance = math.hypot(
            float(left.x) - center_x,
            float(left.y) - center_y,
        )
        right_distance = math.hypot(
            float(right.x) - center_x,
            float(right.y) - center_y,
        )
        if abs(left_distance - right_distance) > _SYMMETRY_TOLERANCE_PX * radius / 50.0:
            return False
    return True


def _is_linear(window) -> bool:
    angles: list[float] = []
    for left, right in zip(window, window[1:], strict=False):
        angles.append(math.degrees(math.atan2(float(right.y) - float(left.y), float(right.x) - float(left.x))))
    if not angles:
        return False
    base = angles[0]
    for angle in angles:
        delta = abs((angle - base + 180.0) % 360.0 - 180.0)
        if min(delta, 180.0 - delta) > _LINEAR_TOLERANCE_DEG:
            return False
    return True


def _is_zigzag(window) -> bool:
    if len(window) < 3:
        return False
    signs: list[int] = []
    for left, right in zip(window, window[1:], strict=False):
        dx = float(right.x) - float(left.x)
        if abs(dx) > 1e-6:
            signs.append(1 if dx > 0 else -1)
    alternating = all(
        signs[index] != signs[index + 1] for index in range(len(signs) - 1)
    )
    if not alternating or len(signs) < 2:
        return False
    turn_angles = _turn_angles(window)
    return bool(turn_angles) and mean(turn_angles) > 60.0


def _turn_angles(window) -> list[float]:
    angles: list[float] = []
    for left, mid, right in zip(window, window[1:], window[2:], strict=False):
        first = math.degrees(
            math.atan2(float(mid.y) - float(left.y), float(mid.x) - float(left.x))
        )
        second = math.degrees(
            math.atan2(float(right.y) - float(mid.y), float(right.x) - float(mid.x))
        )
        delta = abs((second - first + 180.0) % 360.0 - 180.0)
        angles.append(delta)
    return angles


def _build_transitions(positioned, windows: list[tuple[int, int, str]]) -> list[PatternTransition]:
    transitions: list[PatternTransition] = []
    for left_window, right_window in zip(windows, windows[1:], strict=False):
        _, _, left_kind = left_window
        right_start_ms, right_end_ms, right_kind = right_window
        if left_kind == right_kind:
            continue
        angle = _mean_turn_angle_at(positioned, right_start_ms)
        if angle <= _CONFUSING_TURN_DEG:
            continue
        penalty = clamp((angle - _CONFUSING_TURN_DEG) / 80.0, 0.0, 1.0)
        transitions.append(
            PatternTransition(
                from_ms=left_window[0],
                to_ms=right_end_ms,
                from_kind=left_kind,
                to_kind=right_kind,
                angle_deg=round(angle, 2),
                penalty=round(penalty, 4),
            )
        )
    return transitions


def _mean_turn_angle_at(positioned, time_ms: int) -> float:
    """Mean turning angle around the object nearest to ``time_ms``."""
    target = min(
        positioned,
        key=lambda item: abs(item.time - time_ms),
    )
    index = positioned.index(target)
    left = max(0, index - 1)
    right = min(len(positioned) - 1, index + 1)
    if right - left < 2:
        return 0.0
    angles = _turn_angles(positioned[left : right + 1])
    return mean(angles) if angles else 0.0

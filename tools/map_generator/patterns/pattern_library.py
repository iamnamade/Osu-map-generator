from __future__ import annotations

import math
import random
from typing import Any, Callable

from ..config import DifficultyPreset
from ..models import SelectedEvent
from ..position_generator import _Point
from ..utils import clamp, shortest_angle_delta

from .pattern_models import PatternType


def generate_single(
    previous: _Point,
    event: SelectedEvent,
    preset: DifficultyPreset,
    angle: float,
    distance: float,
    rng: random.Random,
) -> _Point:
    """Single note placement."""
    jitter = (rng.random() - 0.5) * 0.15
    return _Point(
        x=previous.x + math.cos(angle + jitter) * distance,
        y=previous.y + math.sin(angle + jitter) * distance,
    )


def generate_double(
    previous: _Point,
    events: list[SelectedEvent],
    index: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> tuple[_Point, _Point]:
    """Two quick consecutive notes at similar position."""
    spread = distance * (0.6 + rng.random() * 0.3)
    offset_angle = 0.3 + rng.random() * 0.4
    sign = 1 if rng.random() >= 0.5 else -1
    p1 = _Point(
        x=previous.x + math.cos(base_angle) * spread * 0.7,
        y=previous.y + math.sin(base_angle) * spread * 0.7,
    )
    p2 = _Point(
        x=p1.x + math.cos(base_angle + sign * offset_angle) * spread * 0.6,
        y=p1.y + math.sin(base_angle + sign * offset_angle) * spread * 0.6,
    )
    return p1, p2


def generate_burst(
    previous: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """3-5 rapid notes in a small cluster."""
    points: list[_Point] = []
    spread = distance * (0.35 + rng.random() * 0.2)
    current = previous
    for i in range(count):
        offset_angle = (i - (count - 1) / 2) * (0.15 + rng.random() * 0.1)
        p = _Point(
            x=current.x + math.cos(base_angle + offset_angle) * spread,
            y=current.y + math.sin(base_angle + offset_angle) * spread,
        )
        points.append(p)
        current = p
    return points


def generate_stream(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Longer sequence of evenly-spaced notes."""
    points: list[_Point] = []
    current = start
    angle_variation = (rng.random() - 0.5) * 0.25
    for i in range(count):
        stream_angle = base_angle + angle_variation * (i / max(1, count - 1))
        stream_dist = distance * (0.85 + rng.random() * 0.3)
        p = _Point(
            x=current.x + math.cos(stream_angle) * stream_dist,
            y=current.y + math.sin(stream_angle) * stream_dist,
        )
        points.append(p)
        current = p
    return points


def generate_jump(
    previous: _Point,
    event: SelectedEvent,
    preset: DifficultyPreset,
    angle: float,
    distance: float,
    rng: random.Random,
) -> _Point:
    """Large isolated jump."""
    return _Point(
        x=previous.x + math.cos(angle) * distance,
        y=previous.y + math.sin(angle) * distance,
    )


def generate_triangle(
    previous: _Point,
    events: list[SelectedEvent],
    index: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> tuple[_Point, _Point, _Point]:
    """Three points forming a triangular shape."""
    spread = distance * (0.6 + rng.random() * 0.2)
    p1 = _Point(
        x=previous.x + math.cos(base_angle - 0.5) * spread,
        y=previous.y + math.sin(base_angle - 0.5) * spread,
    )
    p2 = _Point(
        x=previous.x + math.cos(base_angle + 0.5) * spread,
        y=previous.y + math.sin(base_angle + 0.5) * spread,
    )
    p3 = _Point(
        x=previous.x + math.cos(base_angle + math.pi - 0.3) * spread * 0.9,
        y=previous.y + math.sin(base_angle + math.pi - 0.3) * spread * 0.9,
    )
    return p1, p2, p3


def generate_arc(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Points following a smooth arc."""
    points: list[_Point] = []
    arc_span = 1.2 + rng.random() * 0.8
    sign = 1 if rng.random() >= 0.5 else -1
    for i in range(count):
        t = i / max(1, count - 1)
        arc_angle = base_angle + sign * arc_span * (t - 0.5)
        arc_dist = distance * (0.8 + t * 0.4)
        p = _Point(
            x=start.x + math.cos(arc_angle) * arc_dist,
            y=start.y + math.sin(arc_angle) * arc_dist,
        )
        points.append(p)
    return points


def generate_zigzag(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Zig-zag pattern alternating left and right."""
    points: list[_Point] = []
    current = start
    zig_angle = 0.8 + rng.random() * 0.6
    for i in range(count):
        sign = 1 if i % 2 == 0 else -1
        p = _Point(
            x=current.x + math.cos(base_angle + sign * zig_angle) * distance,
            y=current.y + math.sin(base_angle + sign * zig_angle) * distance,
        )
        points.append(p)
        current = p
    return points


def generate_wave(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Smooth wave pattern with gradual direction changes."""
    points: list[_Point] = []
    current = start
    wave_amplitude = 0.4 + rng.random() * 0.4
    for i in range(count):
        wave_offset = wave_amplitude * math.sin(2 * math.pi * i / max(1, count - 1))
        p = _Point(
            x=current.x + math.cos(base_angle + wave_offset) * distance,
            y=current.y + math.sin(base_angle + wave_offset) * distance,
        )
        points.append(p)
        current = p
    return points


def generate_staircase(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Staircase pattern with gradual stepping."""
    points: list[_Point] = []
    current = start
    step_angle = 0.6 + rng.random() * 0.3
    for i in range(count):
        sign = 1 if rng.random() >= 0.3 else -1
        p = _Point(
            x=current.x + math.cos(base_angle) * distance * 0.7
            + math.cos(base_angle + math.pi / 2 * sign) * distance * 0.3,
            y=current.y + math.sin(base_angle) * distance * 0.7
            + math.sin(base_angle + math.pi / 2 * sign) * distance * 0.3,
        )
        points.append(p)
        current = p
    return points


def generate_back_and_forth(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Back-and-forth pattern alternating along the same line."""
    points: list[_Point] = []
    current = start
    for i in range(count):
        sign = -1 if i % 2 == 0 else 1
        p = _Point(
            x=current.x + math.cos(base_angle) * distance * sign,
            y=current.y + math.sin(base_angle) * distance * sign,
        )
        points.append(p)
        current = p
    return points


def generate_fan(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Fan pattern radiating from a central point."""
    points: list[_Point] = []
    fan_span = 1.5 + rng.random() * 1.0
    sign = 1 if rng.random() >= 0.5 else -1
    for i in range(count):
        t = i / max(1, count - 1) if count > 1 else 0.5
        fan_angle = base_angle + sign * fan_span * (t - 0.5)
        fan_dist = distance * (0.7 + t * 0.6)
        p = _Point(
            x=start.x + math.cos(fan_angle) * fan_dist,
            y=start.y + math.sin(fan_angle) * fan_dist,
        )
        points.append(p)
    return points


def generate_spiral(
    start: _Point,
    events: list[SelectedEvent],
    index: int,
    count: int,
    preset: DifficultyPreset,
    base_angle: float,
    distance: float,
    rng: random.Random,
) -> list[_Point]:
    """Small spiral pattern."""
    points: list[_Point] = []
    current = start
    for i in range(count):
        spiral_angle = base_angle + i * (0.6 + rng.random() * 0.3)
        spiral_dist = distance * (0.3 + i * 0.15)
        p = _Point(
            x=current.x + math.cos(spiral_angle) * spiral_dist,
            y=current.y + math.sin(spiral_angle) * spiral_dist,
        )
        points.append(p)
        current = p
    return points


def generate_center_recovery(
    previous: _Point,
    event: SelectedEvent,
    preset: DifficultyPreset,
    center_x: float,
    center_y: float,
    distance: float,
    rng: random.Random,
) -> _Point:
    """Move toward center of playfield."""
    angle = math.atan2(center_y - previous.y, center_x - previous.x)
    recovery_dist = min(distance * 0.8, math.hypot(center_x - previous.x, center_y - previous.y) * 0.6)
    return _Point(
        x=previous.x + math.cos(angle) * recovery_dist,
        y=previous.y + math.sin(angle) * recovery_dist,
    )

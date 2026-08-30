from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import DifficultyPreset
from ..position_generator import PLAYFIELD_CENTER, PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH
from ..utils import clamp
from .pattern_models import HeatmapCell, PlayfieldHeatmap


@dataclass(frozen=True)
class SpacingConfig:
    """Tunable parameters for difficulty-aware spacing."""

    easy_distance_multiplier: float = 0.6
    normal_distance_multiplier: float = 1.0
    hard_distance_multiplier: float = 1.4
    energy_influence: float = 0.3
    emphasis_bonus: float = 0.25
    heatmap_penalty_strength: float = 0.2
    min_distance_px: float = 20.0


DEFAULT_SPACING_CONFIG = SpacingConfig()


def compute_difficulty_spacing(
    base_jump_distance: float,
    event_energy: float,
    is_emphasis: bool,
    preset: DifficultyPreset,
    config: SpacingConfig = DEFAULT_SPACING_CONFIG,
    kiai_confidence: float = 0.0,
    in_kiai: bool = False,
) -> float:
    """Compute the target spacing for a placement, scaled by difficulty.

    Higher difficulty -> larger spacing.
    Higher energy -> larger spacing.
    Emphasis events -> larger spacing.
    Kiai sections -> wider spacing (chorus boost).
    """
    # Difficulty multiplier
    if preset.name == "easy":
        diff_mult = config.easy_distance_multiplier
    elif preset.name == "hard":
        diff_mult = config.hard_distance_multiplier
    else:
        diff_mult = config.normal_distance_multiplier

    # Energy scaling
    energy_scale = 1.0 + (event_energy - 0.5) * config.energy_influence

    # Emphasis bonus
    emphasis_scale = 1.0 + (config.emphasis_bonus if is_emphasis else 0.0)

    # Kiai section boost: widen spacing during chorus/high-energy sections
    kiai_scale = 1.0
    if in_kiai and kiai_confidence > 0.0:
        # Up to 20% wider jumps during confident kiai sections
        kiai_scale = 1.0 + kiai_confidence * 0.20

    spacing = base_jump_distance * diff_mult * energy_scale * emphasis_scale * kiai_scale
    return max(config.min_distance_px, spacing)


def select_balanced_position(
    candidates: list[tuple[float, float, float]],  # (score, x, y)
    heatmap: PlayfieldHeatmap,
    preset: DifficultyPreset,
    rng: object,
    config: SpacingConfig = DEFAULT_SPACING_CONFIG,
) -> tuple[float, float, float] | None:
    """Select the best candidate position considering heatmap balance."""
    if not candidates:
        return None

    scored: list[tuple[float, float, float, float]] = []
    for candidate_score, x, y in candidates:
        # Apply heatmap penalty to overused regions
        col = min(heatmap.grid_cols - 1, max(0, int(x / PLAYFIELD_WIDTH * heatmap.grid_cols)))
        row = min(heatmap.grid_rows - 1, max(0, int(y / PLAYFIELD_HEIGHT * heatmap.grid_rows)))
        cell = heatmap.cells[row][col]
        heatmap_penalty = cell.count * config.heatmap_penalty_strength + cell.recent_count * 2.0

        # Edge/border penalty
        edge_x = min(x, PLAYFIELD_WIDTH - x)
        edge_y = min(y, PLAYFIELD_HEIGHT - y)
        edge_penalty = max(0, 12 - min(edge_x, edge_y)) * 2 if min(edge_x, edge_y) < 12 else 0

        final_score = candidate_score - heatmap_penalty - edge_penalty
        scored.append((final_score, x, y, candidate_score))

    if not scored:
        return None

    scored.sort(key=lambda s: (-s[0], s[1], s[2]))
    best = scored[0]
    return (best[0], best[1], best[2])


def build_playfield_heatmap(
    existing_x: list[float],
    existing_y: list[float],
    rows: int = 6,
    cols: int = 8,
) -> PlayfieldHeatmap:
    """Build a heatmap from existing object positions."""
    heatmap = PlayfieldHeatmap(grid_rows=rows, grid_cols=cols)
    for x, y in zip(existing_x, existing_y):
        heatmap.record(x, y)
    return heatmap


def compute_spatial_balance(x_coords: list[float], y_coords: list[float]) -> float:
    """Score spatial balance (0-100, higher = more balanced)."""
    if len(x_coords) < 4:
        return 100.0

    # Check left/right balance
    left_count = sum(1 for x in x_coords if x < PLAYFIELD_WIDTH / 2)
    right_count = len(x_coords) - left_count
    lr_balance = 1.0 - abs(left_count - right_count) / max(1, len(x_coords))

    # Check top/bottom balance
    top_count = sum(1 for y in y_coords if y < PLAYFIELD_HEIGHT / 2)
    bottom_count = len(y_coords) - top_count
    tb_balance = 1.0 - abs(top_count - bottom_count) / max(1, len(y_coords))

    # Center avoidance (don't cluster)
    center_count = sum(
        1 for x, y in zip(x_coords, y_coords)
        if PLAYFIELD_WIDTH * 0.3 <= x <= PLAYFIELD_WIDTH * 0.7
        and PLAYFIELD_HEIGHT * 0.3 <= y <= PLAYFIELD_HEIGHT * 0.7
    )
    center_ratio = center_count / max(1, len(x_coords))
    center_score = 1.0 - abs(center_ratio - 0.3) / 0.7

    return (lr_balance * 0.4 + tb_balance * 0.3 + center_score * 0.3) * 100.0


def compute_distance_for_energy(
    energy: float,
    min_dist: float,
    max_dist: float,
    preferred_dist: float,
) -> float:
    """Compute a comfortable distance for a given energy level."""
    t = clamp((energy - 0.1) / 0.7, 0.0, 1.0)
    return min_dist + (preferred_dist - min_dist) * t if t < 0.5 else preferred_dist + (max_dist - preferred_dist) * (t - 0.5) * 2


def compute_stack_offset(
    object_index: int,
    time_ms: int,
    previous_times: list[int],
    beat_interval_ms: int,
) -> tuple[float, float]:
    """Compute the (dx, dy) stack offset for objects that overlap in position.

    When two objects are very close in time (within 1/4 beat of each other)
    and would land at the same position, they need stack offsets to avoid
    visual overlap. osu! uses a standard stack offset formula based on the
    stack distance and object index.

    Returns (offset_x, offset_y) in osu pixels.
    """
    if not previous_times or beat_interval_ms <= 0:
        return (0.0, 0.0)

    stack_distance = 3.0  # standard osu! stack distance threshold
    half_beat = beat_interval_ms / 2
    quarter_beat = beat_interval_ms / 4

    # Check if this object overlaps with any recent object (within 1/4 beat)
    offset_index = 0
    for prev_idx, prev_time in enumerate(reversed(previous_times[-8:])):
        gap = abs(time_ms - prev_time)
        if gap <= quarter_beat and gap >= 0:
            # Count consecutive overlapping objects for the stack level
            offset_index += 1
        elif gap > half_beat:
            break

    if offset_index == 0:
        return (0.0, 0.0)

    # osu! stack offset: alternating x/y offset based on stack index
    direction = offset_index % 2  # 0=x, 1=y
    magnitude = stack_distance * offset_index
    if direction == 0:
        return (magnitude, 0.0)
    else:
        return (0.0, magnitude)


def anti_center_bias(
    x: float,
    y: float,
    heatmap: PlayfieldHeatmap,
    preset_name: str,
) -> float:
    """Compute an anti-center-stacking penalty.

    Returns a penalty (0-15) that increases when placing objects too
    close to the playfield center if the center is already overused.
    """
    center_x = PLAYFIELD_WIDTH / 2
    center_y = PLAYFIELD_HEIGHT / 2
    dist_to_center = math.hypot(x - center_x, y - center_y)

    # Check how many recent objects are near the center
    center_zone_half = PLAYFIELD_WIDTH * 0.18  # center zone = 36% of width
    center_count = 0
    for row_cells in heatmap.cells:
        for cell in row_cells:
            # Approximate cell center
            cell_x = (cell.col + 0.5) * PLAYFIELD_WIDTH / heatmap.grid_cols
            cell_y = (cell.row + 0.5) * PLAYFIELD_HEIGHT / heatmap.grid_rows
            cell_dist = math.hypot(cell_x - center_x, cell_y - center_y)
            if cell_dist < center_zone_half * 1.5:
                center_count += cell.recent_count

    if center_count == 0 or dist_to_center > center_zone_half * 1.2:
        return 0.0

    # Penalty scales with how overused the center is
    penalty = min(15.0, center_count * 3.0)
    # Reduce penalty if we're far from center (good)
    if dist_to_center > center_zone_half:
        penalty *= 0.3

    return penalty


def playfield_boundary_bonus(
    x: float, y: float, total_objects: int, object_index: int
) -> float:
    """Reward placements near playfield boundaries for full grid usage.

    Ensures the generator doesn't just use the comfortable center zone.
    Returns a small bonus (0-8) for edge placements.
    """
    if total_objects < 4:
        return 0.0

    edge_margin = 60.0  # pixels from edge to qualify
    near_left = x < edge_margin
    near_right = x > PLAYFIELD_WIDTH - edge_margin
    near_top = y < edge_margin
    near_bottom = y > PLAYFIELD_HEIGHT - edge_margin

    is_near_edge = near_left or near_right or near_top or near_bottom

    # Only reward if we haven't been near edges recently
    # Use the object index to create a periodic reward pattern
    period = max(3, total_objects // 6)
    should_explore_edge = (object_index % period) < (period // 2)

    if is_near_edge and should_explore_edge:
        return 5.0
    elif not is_near_edge and not should_explore_edge:
        # Mildly discourage staying in the center when we should explore
        return -2.0

    return 0.0

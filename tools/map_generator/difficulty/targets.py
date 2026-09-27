from __future__ import annotations

from dataclasses import dataclass

from .models import DifficultyTarget

# Star-rating ranges and profile targets derived from the existing presets.
# These calibrate the custom star model so each difficulty lands inside its
# expected band. Insane/Expert/Custom are provided as reference profiles for
# the rebalancer and report even though the generator only produces
# easy/normal/hard today.

EASY_TARGET = DifficultyTarget(
    name="easy",
    star_range=(1.0, 2.6),
    density_target=1.1,
    jump_target=95.0,
    speed_target=470.0,
    reading_target=2.2,
    tolerance=0.8,
)

NORMAL_TARGET = DifficultyTarget(
    name="normal",
    star_range=(2.2, 3.9),
    density_target=1.5,
    jump_target=135.0,
    speed_target=660.0,
    reading_target=3.8,
    tolerance=0.9,
)

HARD_TARGET = DifficultyTarget(
    name="hard",
    star_range=(3.6, 5.4),
    density_target=2.4,
    jump_target=175.0,
    speed_target=860.0,
    reading_target=5.2,
    tolerance=1.0,
)

INSANE_TARGET = DifficultyTarget(
    name="insane",
    star_range=(5.2, 6.8),
    density_target=3.0,
    jump_target=225.0,
    speed_target=1050.0,
    reading_target=6.4,
    tolerance=1.1,
)

EXPERT_TARGET = DifficultyTarget(
    name="expert",
    star_range=(6.6, 8.4),
    density_target=3.8,
    jump_target=270.0,
    speed_target=1250.0,
    reading_target=7.4,
    tolerance=1.2,
)

CUSTOM_TARGET = DifficultyTarget(
    name="custom",
    star_range=(0.8, 8.0),
    density_target=2.2,
    jump_target=170.0,
    speed_target=820.0,
    reading_target=4.6,
    tolerance=1.6,
)

DIFFICULTY_TARGETS: dict[str, DifficultyTarget] = {
    target.name: target
    for target in (
        EASY_TARGET,
        NORMAL_TARGET,
        HARD_TARGET,
        INSANE_TARGET,
        EXPERT_TARGET,
        CUSTOM_TARGET,
    )
}

# Preset name -> default target profile name.
PRESET_TO_TARGET: dict[str, str] = {
    "easy": "easy",
    "normal": "normal",
    "hard": "hard",
}


def get_difficulty_target(name: str) -> DifficultyTarget:
    try:
        return DIFFICULTY_TARGETS[name]
    except KeyError as error:
        allowed = ", ".join(sorted(DIFFICULTY_TARGETS))
        raise ValueError(f'Unsupported difficulty target "{name}". Expected one of: {allowed}.') from error


def resolve_target_for_preset(preset_name: str) -> DifficultyTarget:
    target_name = PRESET_TO_TARGET.get(preset_name)
    if target_name is None:
        raise ValueError(f'Unsupported difficulty preset "{preset_name}".')
    return DIFFICULTY_TARGETS[target_name]


def build_custom_target(
    target_star: float | None,
    min_star: float | None,
    max_star: float | None,
) -> DifficultyTarget:
    """Build a custom DifficultyTarget from user star values (Phase 19).

    Validates the band: 0.5 <= min <= target <= max <= 12.0. Raises
    ValueError with a readable message for impossible combinations instead of
    silently rewriting the user's values.
    """
    if target_star is None:
        target_star = 3.0
    if min_star is None:
        min_star = max(0.5, target_star - 1.0)
    if max_star is None:
        max_star = min(12.0, target_star + 1.0)

    if not all(
        isinstance(value, (int, float)) and value == value
        for value in (target_star, min_star, max_star)
    ):
        raise ValueError("Custom difficulty values must be finite numbers.")
    if not (0.5 <= min_star <= target_star <= max_star <= 12.0):
        raise ValueError(
            "Custom difficulty range is impossible: the minimum star rating "
            "must stay within 0.5-12.0 and min <= target <= max "
            f"(got min {min_star:.2f}, target {target_star:.2f}, max {max_star:.2f})."
        )

    center = (min_star + max_star) / 2.0
    return DifficultyTarget(
        name="custom",
        star_range=(round(min_star, 2), round(max_star, 2)),
        density_target=round(0.8 + center * 0.28, 3),
        jump_target=round(60.0 + center * 30.0, 3),
        speed_target=round(300.0 + center * 130.0, 3),
        reading_target=round(1.0 + center * 0.72, 3),
        tolerance=1.6,
    )


def is_target_match(star_rating: float, target: DifficultyTarget) -> bool:
    return target.star_range[0] <= star_rating <= target.star_range[1]


@dataclass(frozen=True)
class TargetDeviation:
    star_rating: float
    target: DifficultyTarget
    direction: str
    magnitude: float

    @property
    def is_within_target(self) -> bool:
        return self.direction == "within"

from __future__ import annotations

from typing import Any

from ..difficulty.common import clamp
from .models import ReplayPlayerProfile

PLAYER_PROFILES: dict[str, ReplayPlayerProfile] = {
    "beginner": ReplayPlayerProfile(
        name="beginner",
        label="Beginner",
        reaction_time_ms=430.0,
        cursor_speed_pps=340.0,
        aim_precision=0.55,
        rhythm_precision=0.5,
        fatigue_growth=1.4,
        recovery_speed=0.5,
        consistency=0.5,
        pattern_memory=0.4,
    ),
    "intermediate": ReplayPlayerProfile(
        name="intermediate",
        label="Intermediate",
        reaction_time_ms=345.0,
        cursor_speed_pps=540.0,
        aim_precision=0.72,
        rhythm_precision=0.7,
        fatigue_growth=1.15,
        recovery_speed=0.7,
        consistency=0.72,
        pattern_memory=0.62,
    ),
    "advanced": ReplayPlayerProfile(
        name="advanced",
        label="Advanced",
        reaction_time_ms=280.0,
        cursor_speed_pps=780.0,
        aim_precision=0.85,
        rhythm_precision=0.84,
        fatigue_growth=1.0,
        recovery_speed=0.85,
        consistency=0.85,
        pattern_memory=0.78,
    ),
    "tournament": ReplayPlayerProfile(
        name="tournament",
        label="Tournament",
        reaction_time_ms=230.0,
        cursor_speed_pps=1080.0,
        aim_precision=0.95,
        rhythm_precision=0.94,
        fatigue_growth=0.85,
        recovery_speed=1.0,
        consistency=0.95,
        pattern_memory=0.92,
    ),
    "custom": ReplayPlayerProfile(
        name="custom",
        label="Custom",
        reaction_time_ms=300.0,
        cursor_speed_pps=640.0,
        aim_precision=0.8,
        rhythm_precision=0.8,
        fatigue_growth=1.0,
        recovery_speed=0.8,
        consistency=0.8,
        pattern_memory=0.7,
    ),
}

# Override keys accepted by resolve_player_profile in camelCase (report JSON
# style) mapped to dataclass field names.
_OVERRIDE_ALIASES: dict[str, str] = {
    "reactionTimeMs": "reaction_time_ms",
    "cursorSpeedPps": "cursor_speed_pps",
    "aimPrecision": "aim_precision",
    "rhythmPrecision": "rhythm_precision",
    "fatigueGrowth": "fatigue_growth",
    "recoverySpeed": "recovery_speed",
    "consistency": "consistency",
    "patternMemory": "pattern_memory",
}


def resolve_player_profile(
    name: str,
    overrides: dict[str, Any] | None = None,
) -> ReplayPlayerProfile:
    """Resolve a named profile and apply optional parameter overrides.

    Overrides may use snake_case field names or camelCase keys from the
    report JSON. Values are clamped to sensible bounds.
    """
    resolved_name = (name or "advanced").lower()
    base = PLAYER_PROFILES.get(resolved_name, PLAYER_PROFILES["advanced"])
    if not overrides:
        return base

    values: dict[str, float] = {}
    for raw_key, raw_value in overrides.items():
        key = _OVERRIDE_ALIASES.get(raw_key, raw_key)
        if not hasattr(base, key):
            continue
        try:
            numeric = float(raw_value)
        except (TypeError, ValueError):
            continue
        if key in ("aim_precision", "rhythm_precision", "consistency", "pattern_memory", "recovery_speed"):
            numeric = clamp(numeric, 0.05, 1.0)
        elif key == "reaction_time_ms":
            numeric = clamp(numeric, 120.0, 900.0)
        elif key == "cursor_speed_pps":
            numeric = clamp(numeric, 120.0, 2500.0)
        elif key == "fatigue_growth":
            numeric = clamp(numeric, 0.2, 3.0)
        values[key] = numeric

    return ReplayPlayerProfile(
        name=base.name,
        label=base.label,
        reaction_time_ms=values.get("reaction_time_ms", base.reaction_time_ms),
        cursor_speed_pps=values.get("cursor_speed_pps", base.cursor_speed_pps),
        aim_precision=values.get("aim_precision", base.aim_precision),
        rhythm_precision=values.get("rhythm_precision", base.rhythm_precision),
        fatigue_growth=values.get("fatigue_growth", base.fatigue_growth),
        recovery_speed=values.get("recovery_speed", base.recovery_speed),
        consistency=values.get("consistency", base.consistency),
        pattern_memory=values.get("pattern_memory", base.pattern_memory),
    )

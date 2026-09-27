"""Phase 22 — Recovery & Player Fatigue Engine.

Models cumulative player stamina and visual reading fatigue from the actual
generated objects (density, jump spacing, stream length), then plans Recovery
Windows (calm-down pacing) after high-strain phrases (``intensify`` ->
``recover``) and enforces post-spinner clearance so the cursor can recenter
before the next object.

Everything is deterministic: every value is a pure function of the supplied
objects, phrase info, and difficulty preset.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from ..config import DifficultyPreset
from ..spinners.spinner_models import (
    FatigueProfile,
    RecoveryWindow,
    SpinnerDiagnostics,
)

# Strain decay per second (higher = faster recovery between objects).
_STRAIN_DECAY_PER_SECOND = 2.0
# Reference cursor travel that produces a full strain unit (px/s).
_STRAIN_REFERENCE_SPEED = 900.0
# Reference spacing weight per difficulty.
_SPACING_WEIGHTS = {"easy": 0.35, "normal": 0.5, "hard": 0.75, "insane": 0.95}

# Difficulty guidelines: minimum spinner duration and post-spinner clearance.
_SPINNER_GUIDELINES = {
    "easy": {"min_duration_ms": 1000, "post_clearance_ms": 600},
    "normal": {"min_duration_ms": 800, "post_clearance_ms": 450},
    "hard": {"min_duration_ms": 600, "post_clearance_ms": 350},
    "insane": {"min_duration_ms": 500, "post_clearance_ms": 280},
}

# Spinner share caps per phrase strategy role (multi-object density harmony).
_ROLE_SPINNER_CAP = {
    "intensify": 0.06,
    "release": 0.12,
    "recover": 0.2,
    "resolve": 0.12,
    "establish": 0.1,
    "transition": 0.14,
    "contrast": 0.08,
    "neutral": 0.1,
}


@dataclass(frozen=True)
class RecoveryEngineConfig:
    strain_decay_per_second: float = _STRAIN_DECAY_PER_SECOND
    strain_reference_speed: float = _STRAIN_REFERENCE_SPEED
    recovery_strain_threshold: float = 0.6
    max_recovery_windows: int = 6

    def to_dict(self) -> dict[str, Any]:
        return {
            "strainDecayPerSecond": self.strain_decay_per_second,
            "strainReferenceSpeed": self.strain_reference_speed,
            "recoveryStrainThreshold": self.recovery_strain_threshold,
            "maxRecoveryWindows": self.max_recovery_windows,
        }


DEFAULT_RECOVERY_CONFIG = RecoveryEngineConfig()


def spinner_guidelines(difficulty: str) -> dict[str, int]:
    """Difficulty-based spinner duration / clearance guidelines.

    Supports easy, normal, hard, and insane. Unknown names fall back to
    normal values so older configurations keep working.
    """
    return _SPINNER_GUIDELINES.get(difficulty, _SPINNER_GUIDELINES["normal"])


def compute_fatigue_profile(
    objects: list[Any],
    *,
    preset: DifficultyPreset,
    config: RecoveryEngineConfig = DEFAULT_RECOVERY_CONFIG,
) -> FatigueProfile:
    """Compute the cumulative fatigue curve across the map's objects.

    Uses the stamina strain model::

        Strain_t = Strain_{t-1} * e^{-lambda * dt} + SpacingWeight * Distance / dt

    ``dt`` is in seconds, ``Distance`` in playfield pixels. The result is
    normalized to 0..1 against the reference strain speed.
    """
    positioned = [
        obj
        for obj in objects
        if getattr(obj, "x", None) is not None and getattr(obj, "y", None) is not None
    ]
    if not positioned:
        return FatigueProfile.empty()

    spacing_weight = _SPACING_WEIGHTS.get(preset.name, 0.5)
    decay = math.exp(-config.strain_decay_per_second)

    timestamps: list[int] = []
    fatigue_scores: list[float] = []
    strain = 0.0
    previous = positioned[0]
    peak_time = int(previous.time)
    peak_value = 0.0

    timestamps.append(int(previous.time))
    fatigue_scores.append(0.0)

    for obj in positioned[1:]:
        dt_seconds = max(0.001, (obj.time - previous.time) / 1000.0)
        distance = math.hypot(obj.x - previous.x, obj.y - previous.y)
        travel_speed = distance / dt_seconds
        strain = strain * decay + spacing_weight * (travel_speed / config.strain_reference_speed)
        normalized = max(0.0, min(1.0, strain))
        timestamps.append(int(obj.time))
        fatigue_scores.append(round(normalized, 4))
        if normalized > peak_value:
            peak_value = normalized
            peak_time = int(obj.time)
        previous = obj

    return FatigueProfile(
        timestamps=timestamps,
        fatigue_scores=fatigue_scores,
        peak_fatigue_time=peak_time,
        peak_fatigue=round(peak_value, 4),
    )


def fatigue_at(profile: FatigueProfile, time_ms: int, window_ms: int = 400) -> float:
    """Average fatigue in a time window around ``time_ms`` (deterministic)."""
    if not profile.timestamps:
        return 0.0
    half = window_ms // 2
    values = [
        score
        for time_stamp, score in zip(profile.timestamps, profile.fatigue_scores, strict=False)
        if abs(time_stamp - time_ms) <= half
    ]
    if not values:
        nearest = min(
            range(len(profile.timestamps)),
            key=lambda index: abs(profile.timestamps[index] - time_ms),
        )
        return float(profile.fatigue_scores[nearest])
    return sum(values) / len(values)


def plan_recovery_windows(
    objects: list[Any],
    *,
    phrase_info: list[Any] | None,
    fatigue: FatigueProfile,
    preset: DifficultyPreset,
    config: RecoveryEngineConfig = DEFAULT_RECOVERY_CONFIG,
) -> list[RecoveryWindow]:
    """Insert calm-down pacing windows after high-strain phrases.

    A recovery window is opened after every ``intensify`` phrase whose peak
    strain exceeds the recovery threshold, covering the following phrase (or
    the tail of the intense phrase when nothing follows). Spinners and other
    low-density content inside these windows are the map's natural rest.

    Deterministic: the phrase order and fatigue values fully determine the
    output.
    """
    windows: list[RecoveryWindow] = []
    if not phrase_info:
        return windows

    ordered = sorted(phrase_info, key=lambda phrase: (phrase.start_ms, phrase.end_ms))
    for index, phrase in enumerate(ordered):
        strategy = getattr(phrase, "strategy", None) or "neutral"
        if strategy != "intensify":
            continue
        window_start = int(phrase.end_ms)
        window_end = int(phrase.end_ms)
        next_phrase = ordered[index + 1] if index + 1 < len(ordered) else None
        if next_phrase is not None:
            window_end = int(next_phrase.end_ms)
        else:
            # Nothing follows: cover the tail of the intense phrase itself.
            window_start = int(phrase.start_ms) + int((phrase.end_ms - phrase.start_ms) * 0.7)

        peak = max(
            (fatigue_at(fatigue, window_start + i * 100) for i in range(0, max(1, (window_end - window_start) // 100))),
            default=0.0,
        )
        if peak < config.recovery_strain_threshold:
            continue

        # Stamina reduction scales with how hard the phrase pushed the player.
        reduction = min(0.8, 0.35 + peak * 0.45)
        windows.append(
            RecoveryWindow(
                start_time=window_start,
                end_time=window_end,
                stamina_reduction_factor=round(reduction, 4),
                reason="post_intense_phrase",
                phrase_id=getattr(phrase, "id", None),
            )
        )
        if len(windows) >= config.max_recovery_windows:
            break
    return windows


def post_spinner_clearance(
    spinner_start_ms: int,
    spinner_end_ms: int,
    next_object_time_ms: int | None,
    *,
    preset: DifficultyPreset,
    min_clearance_ms: int | None = None,
) -> tuple[bool, str]:
    """Verify the post-spinner clearance before the next object.

    Returns (ok, reason). A spinner must leave the player enough time to stop
    spinning and recenter the cursor before the next object — this prevents
    off-screen or unreadable next-object snaps right after a spinner ends.
    """
    if next_object_time_ms is None:
        return True, ""
    clearance = next_object_time_ms - spinner_end_ms
    required = (
        min_clearance_ms
        if min_clearance_ms is not None
        else spinner_guidelines(preset.name)["post_clearance_ms"]
    )
    if clearance < required:
        return False, (
            f"Next object arrives {clearance}ms after spinner end, below the "
            f"{required}ms post-spinner clearance."
        )
    return True, ""


def analyze_density_harmony(
    objects: list[Any],
    *,
    phrase_info: list[Any] | None,
    difficulty: str = "normal",
) -> dict[str, Any]:
    """Balance circle / slider / spinner distributions per phrase role.

    Returns a report with per-role object type counts, spinner share, and any
    harmony violations (e.g. spinners flooding an ``intensify`` phrase).
    """
    if not phrase_info:
        return {"roles": {}, "violations": []}

    roles: dict[str, dict[str, Any]] = {}
    phrase_by_range = sorted(phrase_info, key=lambda phrase: phrase.start_ms)

    def role_for(time_ms: int) -> str | None:
        for phrase in phrase_by_range:
            if phrase.start_ms <= time_ms < phrase.end_ms:
                return getattr(phrase, "strategy", None) or "neutral"
        return None

    for obj in objects:
        role = role_for(int(obj.time))
        if role is None:
            continue
        entry = roles.setdefault(
            role,
            {"circle": 0, "slider": 0, "spinner": 0, "total": 0},
        )
        entry["total"] += 1
        if obj.type == "circle":
            entry["circle"] += 1
        elif obj.type == "slider":
            entry["slider"] += 1
        elif obj.type == "spinner":
            entry["spinner"] += 1

    violations: list[dict[str, str]] = []
    for role, counts in sorted(roles.items()):
        total = counts["total"]
        spinner_share = counts["spinner"] / total if total else 0.0
        cap = _ROLE_SPINNER_CAP.get(role, 0.1)
        if spinner_share > cap and counts["spinner"] >= 2:
            violations.append(
                {
                    "role": role,
                    "message": (
                        f"{role} phrases contain {counts['spinner']} spinners "
                        f"({spinner_share:.0%} of {total} objects, cap {cap:.0%})."
                    ),
                }
            )

    return {
        "roles": roles,
        "violations": violations,
    }


def attach_recovery_diagnostics(
    diagnostics: SpinnerDiagnostics,
    *,
    fatigue: FatigueProfile,
    recovery_windows: list[RecoveryWindow],
    harmony: dict[str, Any],
) -> SpinnerDiagnostics:
    """Write Phase 22 recovery / fatigue data into spinner diagnostics."""
    diagnostics.fatigue_peak = fatigue.peak_fatigue
    diagnostics.fatigue_peak_time_ms = fatigue.peak_fatigue_time
    diagnostics.recovery_windows = [window.to_dict() for window in recovery_windows]
    diagnostics.harmony = harmony
    return diagnostics

from __future__ import annotations

from ..config import DifficultyPreset
from .spinner_models import SpinnerMusicalContext


def compute_spinner_window(
    *,
    gap_start_ms: int,
    gap_end_ms: int,
    context: SpinnerMusicalContext,
    preset: DifficultyPreset,
    min_duration_ms: int | None = None,
    max_duration_ms: int | None = None,
    recovery_after_ms: int | None = None,
    entry_buffer_ms: int | None = None,
) -> tuple[int, int] | None:
    """Compute the spinner start/end window inside an empty gap.

    The spinner must respect the available gap, the difficulty caps, and
    keep enough recovery time after the spinner before the next object.

    Args:
        gap_start_ms: time after the previous object's end (exclusive)
        gap_end_ms: time before the next object's start (exclusive)
        context: musical context
        preset: difficulty preset
        min_duration_ms: override for the minimum spinner length
        max_duration_ms: override for the maximum spinner length
        recovery_after_ms: how much recovery time to leave before the next object
        entry_buffer_ms: how much breathing room to leave after the previous object

    Returns:
        (start_ms, end_ms) or None if the gap cannot host a spinner.
    """
    min_ms = min_duration_ms if min_duration_ms is not None else preset.spinner_min_duration_ms
    max_ms = max_duration_ms if max_duration_ms is not None else preset.spinner_max_duration_ms
    # The spinner must also respect the preset's global min gap (start-to-start
    # against the previous object and spinner-start-to-next-object), otherwise
    # the rhythm validator flags RHYTHM_GAP_BELOW_MINIMUM.
    min_gap = max(0, int(getattr(preset, 'min_gap_ms', 0)))
    recovery = (
        recovery_after_ms
        if recovery_after_ms is not None
        else max(preset.spinner_recovery_after_ms, min_gap)
    )
    entry = (
        entry_buffer_ms
        if entry_buffer_ms is not None
        else max(preset.spinner_entry_buffer_ms, min_gap)
    )

    available = gap_end_ms - gap_start_ms
    if available < min_ms + recovery + entry:
        return None

    raw_start = gap_start_ms + entry
    raw_end = gap_end_ms - recovery
    raw_duration = raw_end - raw_start

    if raw_duration < min_ms:
        return None

    # Difficulty scaling: easy uses shorter spinners, hard can use longer ones.
    if preset.name == "easy":
        target = min(max_ms, int(raw_duration * 0.6), preset.spinner_easy_target_ms)
    elif preset.name == "normal":
        target = min(max_ms, int(raw_duration * 0.75), preset.spinner_normal_target_ms)
    else:
        target = min(max_ms, int(raw_duration * 0.85), preset.spinner_hard_target_ms)

    target = max(min_ms, target)

    if target > raw_duration:
        return None

    # Snap boundaries to musical anchors when available (beats/onsets/energy frames).
    start_ms = _snap_start(raw_start, target, context, preset)
    end_ms = start_ms + target
    end_ms = min(end_ms, raw_end)

    # Enforce integer timestamps and strict endTime > time.
    start_ms = int(round(start_ms))
    end_ms = int(round(end_ms))
    if end_ms <= start_ms:
        end_ms = start_ms + min_ms

    if end_ms - start_ms < min_ms:
        return None

    return start_ms, end_ms


def _snap_start(
    raw_start_ms: int,
    duration_ms: int,
    context: SpinnerMusicalContext,
    preset: DifficultyPreset,
) -> int:
    """Snap the spinner start to a nearby meaningful musical boundary."""
    beat_interval_ms = 60000 / max(60.0, context.bpm) if context.bpm > 0 else 500

    candidates: list[tuple[int, float]] = []

    for onset_time in context.onset_times:
        delta = abs(onset_time - raw_start_ms)
        if delta <= beat_interval_ms * 1.1:
            candidates.append((int(onset_time), delta / (beat_interval_ms * 1.1)))

    # Prefer snapping to a beat-aligned grid when possible.
    grid_size = beat_interval_ms
    grid_snapped = int(round(raw_start_ms / grid_size)) * grid_size
    grid_snapped_int = int(round(grid_snapped))
    grid_delta = abs(grid_snapped_int - raw_start_ms)
    if grid_delta <= beat_interval_ms * 0.45:
        candidates.append((grid_snapped_int, grid_delta / (beat_interval_ms * 0.45) * 0.8))

    # Energy frame boundaries
    for frame in context.energy_frames:
        frame_time = int(round(frame["timeMs"]))
        delta = abs(frame_time - raw_start_ms)
        if delta <= beat_interval_ms * 0.5:
            candidates.append((frame_time, delta / (beat_interval_ms * 0.5) + 0.2))

    if not candidates:
        return int(round(raw_start_ms))

    candidates.sort(key=lambda item: (item[1], item[0]))
    snapped = candidates[0][0]

    # Never snap beyond the raw window minus the minimum duration.
    return int(round(max(raw_start_ms, min(snapped, raw_start_ms + int(duration_ms * 0.5)))))

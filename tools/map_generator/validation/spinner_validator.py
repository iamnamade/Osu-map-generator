from __future__ import annotations

from dataclasses import dataclass

from ..config import DifficultyPreset
from ..models import AudioAnalysis
from .models import ParsedBeatmap, ValidationIssue


@dataclass(frozen=True)
class SpinnerValidationResult:
    metrics: dict[str, int | float]
    issues: list[ValidationIssue]


def validate_spinners(
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
) -> SpinnerValidationResult:
    """Validate spinner objects against spinner-specific rules.

    Rules:
    - minimum duration
    - maximum duration
    - no overlap with other objects (spinners own their time range)
    - timing consistency (start on a beat/onset boundary)
    - transition safety (recovery time after the spinner)
    - difficulty consistency (duration fits the difficulty)
    """
    issues: list[ValidationIssue] = []
    spinners = [item for item in beatmap.objects if item.type == "spinner"]
    durations: list[int] = []

    for spinner in spinners:
        duration_ms = spinner.end_time - spinner.time if spinner.end_time is not None else 0
        durations.append(duration_ms)

        if duration_ms < preset.spinner_min_duration_ms:
            issues.append(
                ValidationIssue(
                    code="SPINNER_TOO_SHORT",
                    severity="warning",
                    message="Spinner duration is below the minimum for this difficulty.",
                    category="structural",
                    object_ids=[spinner.id],
                    start_time_ms=spinner.time,
                    end_time_ms=spinner.end_time,
                    measured_value=float(duration_ms),
                    allowed_value=float(preset.spinner_min_duration_ms),
                    suggestion="Lengthen the spinner or remove it if the music does not support it.",
                )
            )

        if duration_ms > preset.spinner_max_duration_ms:
            issues.append(
                ValidationIssue(
                    code="SPINNER_TOO_LONG",
                    severity="warning",
                    message="Spinner duration exceeds the maximum for this difficulty.",
                    category="structural",
                    object_ids=[spinner.id],
                    start_time_ms=spinner.time,
                    end_time_ms=spinner.end_time,
                    measured_value=float(duration_ms),
                    allowed_value=float(preset.spinner_max_duration_ms),
                    suggestion="Shorten the spinner to keep it within the difficulty envelope.",
                )
            )

        # Overlap with the previous object: spinner start must not cut into it.
        previous = _previous_object(beatmap, spinner)
        if previous is not None:
            previous_end = getattr(previous, "end_time", None)
            previous_end_ms = previous_end if previous_end is not None else previous.time
            if spinner.time < previous_end_ms:
                issues.append(
                    ValidationIssue(
                        code="SPINNER_OVERLAPS_PREVIOUS",
                        severity="critical",
                        message="Spinner start overlaps the previous object.",
                        category="structural",
                        object_ids=[previous.id, spinner.id],
                        start_time_ms=previous.time,
                        end_time_ms=spinner.time,
                        suggestion="Move the spinner start after the previous object ends.",
                    )
                )
            elif spinner.time - previous_end_ms < preset.spinner_entry_buffer_ms:
                issues.append(
                    ValidationIssue(
                        code="SPINNER_ENTRY_TOO_TIGHT",
                        severity="warning",
                        message="Not enough breathing room before the spinner starts.",
                        category="structural",
                        object_ids=[spinner.id],
                        start_time_ms=previous_end_ms,
                        end_time_ms=spinner.time,
                        measured_value=float(spinner.time - previous_end_ms),
                        allowed_value=float(preset.spinner_entry_buffer_ms),
                        suggestion="Push the spinner later so players have time to react.",
                    )
                )

        # Overlap with the next object: spinner end must not cut into it.
        next_object = _next_object(beatmap, spinner)
        if next_object is not None:
            if spinner.end_time > next_object.time:
                issues.append(
                    ValidationIssue(
                        code="SPINNER_OVERLAPS_NEXT",
                        severity="critical",
                        message="Spinner end overlaps the next object.",
                        category="structural",
                        object_ids=[spinner.id, next_object.id],
                        start_time_ms=spinner.time,
                        end_time_ms=spinner.end_time,
                        suggestion="Shorten the spinner so it ends before the next object.",
                    )
                )
            elif next_object.time - spinner.end_time < preset.spinner_recovery_after_ms:
                issues.append(
                    ValidationIssue(
                        code="SPINNER_RECOVERY_TOO_TIGHT",
                        severity="warning",
                        message="Not enough recovery time after the spinner before the next object.",
                        category="structural",
                        object_ids=[spinner.id, next_object.id],
                        start_time_ms=spinner.end_time,
                        end_time_ms=next_object.time,
                        measured_value=float(next_object.time - spinner.end_time),
                        allowed_value=float(preset.spinner_recovery_after_ms),
                        suggestion="End the spinner earlier so players can recover before the next object.",
                    )
                )

        # Timing consistency: spinner start should be near a beat or onset.
        beat_delta = _nearest_event_delta(spinner.time, analysis.beats)
        onset_delta = _nearest_event_delta(spinner.time, analysis.onsets)
        best_delta = min(
            delta for delta in (beat_delta, onset_delta) if delta is not None
        )
        if best_delta is not None and best_delta > 140:
            issues.append(
                ValidationIssue(
                    code="SPINNER_START_MISALIGNED",
                    severity="warning",
                    message="Spinner start is not aligned to a beat or onset.",
                    category="timing",
                    object_ids=[spinner.id],
                    start_time_ms=spinner.time,
                    measured_value=float(best_delta),
                    allowed_value=140.0,
                    suggestion="Snap the spinner start to the nearest beat or onset.",
                )
            )

        # Difficulty consistency: easy maps should not contain very long spinners.
        if preset.name == "easy" and duration_ms > preset.spinner_hard_target_ms:
            issues.append(
                ValidationIssue(
                    code="SPINNER_DIFFICULTY_INCONSISTENT",
                    severity="warning",
                    message="Spinner duration is much longer than expected for this difficulty.",
                    category="difficultyConsistency",
                    object_ids=[spinner.id],
                    start_time_ms=spinner.time,
                    end_time_ms=spinner.end_time,
                    measured_value=float(duration_ms),
                    allowed_value=float(preset.spinner_hard_target_ms),
                    suggestion="Shorten the spinner or move it to a harder difficulty.",
                )
            )

    return SpinnerValidationResult(
        metrics={
            "spinnerCount": len(spinners),
            "averageDurationMs": round(sum(durations) / len(durations), 2) if durations else 0.0,
            "longestDurationMs": max(durations) if durations else 0,
            "shortestDurationMs": min(durations) if durations else 0,
        },
        issues=issues,
    )


def _previous_object(beatmap: ParsedBeatmap, spinner: object) -> object | None:
    spinner_time = getattr(spinner, "time")
    candidates = [item for item in beatmap.objects if item.time < spinner_time]
    return max(candidates, key=lambda item: item.time) if candidates else None


def _next_object(beatmap: ParsedBeatmap, spinner: object) -> object | None:
    spinner_end = getattr(spinner, "end_time")
    candidates = [item for item in beatmap.objects if item.time >= spinner_end]
    return min(candidates, key=lambda item: item.time) if candidates else None


def _nearest_event_delta(
    time_ms: int,
    events: list[object],
) -> int | None:
    if not events:
        return None
    return min(abs(event.time_ms - time_ms) for event in events)

from __future__ import annotations

from dataclasses import dataclass

from ..config import DifficultyPreset
from ..models import AudioAnalysis
from .models import DensityMetrics, DensityWindowDiagnostic, MovementPairDiagnostic, ParsedBeatmap, TimingObjectDiagnostic, ValidationIssue

WINDOW_SIZE_MS = 2_000
ANALYSIS_WINDOW_SIZES = (2_000, 4_000, 8_000)


@dataclass(frozen=True)
class DensityValidationResult:
    metrics: DensityMetrics
    issues: list[ValidationIssue]


def validate_density(
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    timing_diagnostics: list[TimingObjectDiagnostic],
    pair_diagnostics: list[MovementPairDiagnostic],
) -> DensityValidationResult:
    issues: list[ValidationIssue] = []
    exported_windows = _build_windows(
        beatmap=beatmap,
        analysis=analysis,
        timing_diagnostics=timing_diagnostics,
        pair_diagnostics=pair_diagnostics,
        window_size_ms=WINDOW_SIZE_MS,
    )

    high_density_low_energy_windows = 0
    low_density_high_energy_windows = 0
    abrupt_density_spikes = 0
    flat_density_despite_energy_change = 0
    target_objects_per_second = 1000 / preset.target_gap_ms if preset.target_gap_ms > 0 else 0.0

    for window in exported_windows:
        if (
            window.objects_per_second > target_objects_per_second * 1.28
            and window.average_audio_energy < preset.quiet_energy_threshold * 1.15
        ):
            high_density_low_energy_windows += 1
            issues.append(
                ValidationIssue(
                    code="DENSITY_HIGH_MAP_LOW_AUDIO",
                    severity="warning",
                    message="Window density is high even though the local audio energy is low.",
                    category="densityConsistency",
                    start_time_ms=window.start_ms,
                    end_time_ms=window.end_ms,
                    measured_value=window.objects_per_second,
                    allowed_value=target_objects_per_second * 1.28,
                    suggestion="Thin the pattern in this lower-energy section.",
                )
            )

        if (
            window.objects_per_second < target_objects_per_second * 0.55
            and window.average_audio_energy > preset.high_energy_threshold * 0.92
        ):
            low_density_high_energy_windows += 1
            issues.append(
                ValidationIssue(
                    code="DENSITY_LOW_MAP_HIGH_AUDIO",
                    severity="warning",
                    message="Window density is low relative to a high-energy audio section.",
                    category="densityConsistency",
                    start_time_ms=window.start_ms,
                    end_time_ms=window.end_ms,
                    measured_value=window.objects_per_second,
                    allowed_value=target_objects_per_second * 0.55,
                    suggestion="Represent more of the musical intensity here.",
                )
            )

    analysis_windows = {
        size: _build_windows(
            beatmap=beatmap,
            analysis=analysis,
            timing_diagnostics=timing_diagnostics,
            pair_diagnostics=pair_diagnostics,
            window_size_ms=size,
        )
        for size in ANALYSIS_WINDOW_SIZES
    }

    for windows in analysis_windows.values():
        for previous, current in zip(windows, windows[1:], strict=False):
            density_difference = abs(current.objects_per_second - previous.objects_per_second)
            energy_difference = abs(current.average_audio_energy - previous.average_audio_energy)
            if (
                min(previous.objects_per_second, current.objects_per_second) > 0
                and max(previous.objects_per_second, current.objects_per_second)
                / min(previous.objects_per_second, current.objects_per_second)
                >= 1.85
                and energy_difference < 0.16
            ):
                abrupt_density_spikes += 1
                issues.append(
                    ValidationIssue(
                        code="DENSITY_UNEXPLAINED_SPIKE",
                        severity="warning",
                        message="A large local density change is not matched by a meaningful energy shift.",
                        category="densityConsistency",
                        start_time_ms=previous.start_ms,
                        end_time_ms=current.end_ms,
                        measured_value=max(previous.objects_per_second, current.objects_per_second),
                        allowed_value=min(previous.objects_per_second, current.objects_per_second) * 1.85,
                        suggestion="Smooth this density transition or justify it with stronger musical emphasis.",
                    )
                )
            elif energy_difference > 0.25 and density_difference < target_objects_per_second * 0.18:
                flat_density_despite_energy_change += 1

    if flat_density_despite_energy_change > 0:
        issues.append(
            ValidationIssue(
                code="DENSITY_FLAT_DESPITE_AUDIO_CHANGE",
                severity="info",
                message="Large energy changes occur while local map density stays almost flat.",
                category="densityConsistency",
                measured_value=float(flat_density_despite_energy_change),
                allowed_value=0.0,
            )
        )

    last_object_time = beatmap.objects[-1].time if beatmap.objects else 0
    ending_gap_ms = max(0, analysis.duration_ms - last_object_time)
    tail_energy = _average_frame_energy(
        analysis=analysis,
        start_ms=max(0, analysis.duration_ms - max(1_600, preset.end_padding_ms * 2)),
        end_ms=analysis.duration_ms,
    )

    if ending_gap_ms > max(preset.end_padding_ms + 350, int(preset.target_gap_ms * 1.4)) and tail_energy > preset.high_energy_threshold * 0.72:
        issues.append(
            ValidationIssue(
                code="DENSITY_EARLY_MAP_END",
                severity="warning",
                message="The map ends well before the audio meaningfully settles down.",
                category="densityConsistency",
                start_time_ms=last_object_time,
                end_time_ms=analysis.duration_ms,
                measured_value=float(ending_gap_ms),
                allowed_value=float(max(preset.end_padding_ms + 350, int(preset.target_gap_ms * 1.4))),
                suggestion="Keep mapping a little farther into the active ending section.",
            )
        )

    if last_object_time > max(0, analysis.duration_ms - preset.end_padding_ms) and tail_energy < preset.quiet_energy_threshold * 1.05:
        issues.append(
            ValidationIssue(
                code="DENSITY_OBJECTS_IN_OUTRO_SILENCE",
                severity="warning",
                message="Objects continue into a quiet outro window.",
                category="densityConsistency",
                start_time_ms=last_object_time,
                measured_value=float(last_object_time),
                allowed_value=float(max(0, analysis.duration_ms - preset.end_padding_ms)),
            )
        )

    metrics = DensityMetrics(
        windows=exported_windows,
        high_density_low_energy_windows=high_density_low_energy_windows,
        low_density_high_energy_windows=low_density_high_energy_windows,
        abrupt_density_spikes=abrupt_density_spikes,
        flat_density_despite_energy_change=flat_density_despite_energy_change,
        ending_gap_ms=ending_gap_ms,
    )
    return DensityValidationResult(metrics=metrics, issues=issues)


def _build_windows(
    *,
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    timing_diagnostics: list[TimingObjectDiagnostic],
    pair_diagnostics: list[MovementPairDiagnostic],
    window_size_ms: int,
) -> list[DensityWindowDiagnostic]:
    windows: list[DensityWindowDiagnostic] = []
    for start_ms in range(0, max(window_size_ms, analysis.duration_ms), window_size_ms):
        end_ms = min(analysis.duration_ms, start_ms + window_size_ms)
        if end_ms <= start_ms:
            continue

        objects_in_window = [item for item in beatmap.objects if start_ms <= item.time < end_ms]
        timing_in_window = [item for item in timing_diagnostics if start_ms <= item.time_ms < end_ms]
        movement_in_window = [item for item in pair_diagnostics if start_ms <= item.to_time_ms < end_ms]
        duration_seconds = (end_ms - start_ms) / 1000

        windows.append(
            DensityWindowDiagnostic(
                start_ms=start_ms,
                end_ms=end_ms,
                objects_per_second=(len(objects_in_window) / duration_seconds) if duration_seconds > 0 else 0.0,
                object_count=len(objects_in_window),
                average_event_strength=_average([item.anchor_strength for item in timing_in_window]),
                average_audio_energy=_average_frame_energy(analysis=analysis, start_ms=start_ms, end_ms=end_ms),
                average_jump_distance=_average([item.distance_px for item in movement_in_window]),
                average_cursor_speed=_average([item.cursor_speed_pps for item in movement_in_window]),
                timing_confidence=_average([item.confidence for item in timing_in_window]),
                issue_count=0,
            )
        )
    return windows


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _average_frame_energy(*, analysis: AudioAnalysis, start_ms: int, end_ms: int) -> float:
    matching_frames = [
        frame.value
        for frame in analysis.energy_frames
        if start_ms <= frame.time_ms < end_ms
    ]
    if matching_frames:
        return sum(matching_frames) / len(matching_frames)

    midpoint = start_ms + max(0, end_ms - start_ms) // 2
    return analysis.energy_at(midpoint)

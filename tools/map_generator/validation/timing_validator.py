from __future__ import annotations

from dataclasses import dataclass

from ..config import DifficultyPreset
from ..models import AudioAnalysis, TimedStrength
from ..utils import clamp
from .models import ParsedBeatmap, TimingMetrics, TimingObjectDiagnostic, ValidationIssue

EXCELLENT_ALIGNMENT_MS = 25
GOOD_ALIGNMENT_MS = 50
ACCEPTABLE_ALIGNMENT_MS = 90
WEAK_ALIGNMENT_MS = 140
MISTIMED_ALIGNMENT_MS = 190
CRITICAL_ALIGNMENT_MS = 250
BIAS_THRESHOLD_MS = 50
WEAK_ANCHOR_STRENGTH = 0.28


@dataclass(frozen=True)
class TimingValidationResult:
    metrics: TimingMetrics
    issues: list[ValidationIssue]
    diagnostics: list[TimingObjectDiagnostic]


def validate_timing(
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
) -> TimingValidationResult:
    issues: list[ValidationIssue] = []
    diagnostics: list[TimingObjectDiagnostic] = []
    beat_deltas: list[int] = []
    onset_deltas: list[int] = []
    anchor_deltas: list[int] = []
    early_bias_count = 0
    late_bias_count = 0
    excellent_alignment_count = 0
    good_alignment_count = 0
    acceptable_alignment_count = 0
    weak_alignment_count = 0
    mistimed_count = 0
    anchor_usage = {"beat": 0, "onset": 0, "none": 0}

    for hit_object in beatmap.objects:
        nearest_beat, beat_delta = _find_nearest_event(hit_object.time, analysis.beats)
        nearest_onset, onset_delta = _find_nearest_event(hit_object.time, analysis.onsets)
        anchor_type, anchor_event, signed_delta = _choose_anchor(
            beat_delta=beat_delta,
            onset_delta=onset_delta,
            nearest_beat=nearest_beat,
            nearest_onset=nearest_onset,
        )
        local_energy = analysis.energy_at(hit_object.time)
        anchor_strength = anchor_event.strength if anchor_event is not None else 0.0
        absolute_anchor_delta = abs(signed_delta) if signed_delta is not None else None
        confidence = _compute_confidence(
            anchor_delta_ms=absolute_anchor_delta,
            anchor_strength=anchor_strength,
            local_energy=local_energy,
        )

        diagnostics.append(
            TimingObjectDiagnostic(
                object_id=hit_object.id,
                time_ms=hit_object.time,
                nearest_beat_delta_ms=beat_delta,
                nearest_onset_delta_ms=onset_delta,
                anchor_type=anchor_type,
                anchor_strength=anchor_strength,
                local_energy=local_energy,
                confidence=confidence,
                signed_delta_ms=signed_delta,
            )
        )

        anchor_usage[anchor_type] += 1

        if beat_delta is not None:
            beat_deltas.append(abs(beat_delta))
        if onset_delta is not None:
            onset_deltas.append(abs(onset_delta))

        if absolute_anchor_delta is None:
            mistimed_count += 1
            issues.append(
                ValidationIssue(
                    code="TIMING_NO_CONVINCING_ANCHOR",
                    severity="error",
                    message="Object has no convincing nearby beat or onset anchor.",
                    category="timing",
                    object_ids=[hit_object.id],
                    start_time_ms=hit_object.time,
                    suggestion="Move the object closer to a detected beat or onset.",
                )
            )
            continue

        anchor_deltas.append(absolute_anchor_delta)

        if absolute_anchor_delta <= EXCELLENT_ALIGNMENT_MS:
            excellent_alignment_count += 1
        elif absolute_anchor_delta <= GOOD_ALIGNMENT_MS:
            good_alignment_count += 1
        elif absolute_anchor_delta <= ACCEPTABLE_ALIGNMENT_MS:
            acceptable_alignment_count += 1
        elif absolute_anchor_delta <= WEAK_ALIGNMENT_MS:
            weak_alignment_count += 1
            issues.append(
                ValidationIssue(
                    code="TIMING_WEAK_ALIGNMENT",
                    severity="warning",
                    message="Object is only weakly aligned to its nearest musical anchor.",
                    category="timing",
                    object_ids=[hit_object.id],
                    start_time_ms=hit_object.time,
                    measured_value=float(absolute_anchor_delta),
                    allowed_value=float(ACCEPTABLE_ALIGNMENT_MS),
                    suggestion="Nudge the object closer to the nearest beat or onset.",
                )
            )
        else:
            mistimed_count += 1
            issues.append(
                ValidationIssue(
                    code="TIMING_MISTIMED_OBJECT",
                    severity="error" if absolute_anchor_delta <= CRITICAL_ALIGNMENT_MS else "critical",
                    message="Object timing is too far from the nearest strong musical anchor.",
                    category="timing",
                    object_ids=[hit_object.id],
                    start_time_ms=hit_object.time,
                    measured_value=float(absolute_anchor_delta),
                    allowed_value=float(WEAK_ALIGNMENT_MS),
                    suggestion="Snap the object toward the strongest nearby beat or onset.",
                )
            )

        if signed_delta is not None and signed_delta <= -BIAS_THRESHOLD_MS:
            early_bias_count += 1
        elif signed_delta is not None and signed_delta >= BIAS_THRESHOLD_MS:
            late_bias_count += 1

        if local_energy < preset.quiet_energy_threshold * 0.75 and anchor_strength < WEAK_ANCHOR_STRENGTH:
            issues.append(
                ValidationIssue(
                    code="TIMING_OBJECT_IN_SILENCE",
                    severity="warning",
                    message="Object lands inside a near-silent section without a strong anchor.",
                    category="timing",
                    object_ids=[hit_object.id],
                    start_time_ms=hit_object.time,
                    measured_value=local_energy,
                    allowed_value=preset.quiet_energy_threshold,
                    suggestion="Remove the object or place it on a clearer musical event.",
                )
            )

        if anchor_type == "onset" and anchor_strength < max(WEAK_ANCHOR_STRENGTH, preset.onset_strength_threshold * 0.85):
            issues.append(
                ValidationIssue(
                    code="TIMING_WEAK_ONSET_REFERENCE",
                    severity="info",
                    message="Object is anchored to a relatively weak onset.",
                    category="timing",
                    object_ids=[hit_object.id],
                    start_time_ms=hit_object.time,
                    measured_value=anchor_strength,
                    allowed_value=preset.onset_strength_threshold,
                    suggestion="Prefer a stronger onset or nearby beat if available.",
                )
            )

    if early_bias_count >= 3 and early_bias_count > late_bias_count and early_bias_count >= max(3, len(beatmap.objects) // 3):
        issues.append(
            ValidationIssue(
                code="TIMING_REPEATED_EARLY_BIAS",
                severity="warning",
                message="Several objects consistently land early relative to their anchors.",
                category="timing",
                measured_value=float(early_bias_count),
                allowed_value=float(max(2, len(beatmap.objects) // 4)),
                suggestion="Shift the affected sequence slightly later.",
            )
        )

    if late_bias_count >= 3 and late_bias_count > early_bias_count and late_bias_count >= max(3, len(beatmap.objects) // 3):
        issues.append(
            ValidationIssue(
                code="TIMING_REPEATED_LATE_BIAS",
                severity="warning",
                message="Several objects consistently land late relative to their anchors.",
                category="timing",
                measured_value=float(late_bias_count),
                allowed_value=float(max(2, len(beatmap.objects) // 4)),
                suggestion="Shift the affected sequence slightly earlier.",
            )
        )

    _append_ignored_strong_event_issues(
        beatmap=beatmap,
        analysis=analysis,
        preset=preset,
        issues=issues,
    )

    metrics = TimingMetrics(
        average_anchor_delta_ms=_average(anchor_deltas),
        average_beat_delta_ms=_average(beat_deltas),
        average_onset_delta_ms=_average(onset_deltas),
        excellent_alignment_count=excellent_alignment_count,
        good_alignment_count=good_alignment_count,
        acceptable_alignment_count=acceptable_alignment_count,
        weak_alignment_count=weak_alignment_count,
        mistimed_count=mistimed_count,
        early_bias_count=early_bias_count,
        late_bias_count=late_bias_count,
        anchor_usage=anchor_usage,
    )

    return TimingValidationResult(
        metrics=metrics,
        issues=issues,
        diagnostics=diagnostics,
    )


def _find_nearest_event(time_ms: int, events: list[TimedStrength]) -> tuple[TimedStrength | None, int | None]:
    if not events:
        return None, None

    nearest = min(events, key=lambda item: abs(item.time_ms - time_ms))
    return nearest, time_ms - nearest.time_ms


def _choose_anchor(
    *,
    beat_delta: int | None,
    onset_delta: int | None,
    nearest_beat: TimedStrength | None,
    nearest_onset: TimedStrength | None,
) -> tuple[str, TimedStrength | None, int | None]:
    beat_score = float("inf")
    onset_score = float("inf")

    if beat_delta is not None and nearest_beat is not None:
        beat_score = abs(beat_delta) - nearest_beat.strength * 22
    if onset_delta is not None and nearest_onset is not None:
        onset_score = abs(onset_delta) - nearest_onset.strength * 24

    if beat_score == float("inf") and onset_score == float("inf"):
        return "none", None, None

    if min(beat_score, onset_score) > MISTIMED_ALIGNMENT_MS + 20:
        return "none", None, None

    if onset_score + 6 < beat_score and nearest_onset is not None:
        return "onset", nearest_onset, onset_delta

    if beat_score <= onset_score and nearest_beat is not None:
        return "beat", nearest_beat, beat_delta

    if nearest_onset is not None:
        return "onset", nearest_onset, onset_delta

    return "beat", nearest_beat, beat_delta


def _compute_confidence(
    *,
    anchor_delta_ms: int | None,
    anchor_strength: float,
    local_energy: float,
) -> float:
    if anchor_delta_ms is None:
        return 0.0

    if anchor_delta_ms <= EXCELLENT_ALIGNMENT_MS:
        delta_score = 1.0
    elif anchor_delta_ms <= GOOD_ALIGNMENT_MS:
        delta_score = 0.88
    elif anchor_delta_ms <= ACCEPTABLE_ALIGNMENT_MS:
        delta_score = 0.68
    elif anchor_delta_ms <= WEAK_ALIGNMENT_MS:
        delta_score = 0.44
    else:
        delta_score = max(0.05, 0.32 - ((anchor_delta_ms - WEAK_ALIGNMENT_MS) / 220))

    return round(
        clamp(delta_score * 0.7 + anchor_strength * 0.2 + local_energy * 0.1, 0.0, 1.0),
        4,
    )


def _append_ignored_strong_event_issues(
    *,
    beatmap: ParsedBeatmap,
    analysis: AudioAnalysis,
    preset: DifficultyPreset,
    issues: list[ValidationIssue],
) -> None:
    strong_events: list[TimedStrength] = []
    strong_events.extend(
        beat for beat in analysis.beats if beat.strength >= preset.strong_beat_threshold
    )
    strong_events.extend(
        onset for onset in analysis.onsets if onset.strength >= preset.onset_strength_threshold + 0.1
    )
    strong_events.sort(key=lambda item: (item.time_ms, -item.strength))

    uncovered_run: list[TimedStrength] = []
    covered_tolerance = ACCEPTABLE_ALIGNMENT_MS

    def flush_run() -> None:
        if len(uncovered_run) < 3:
            uncovered_run.clear()
            return

        span_ms = uncovered_run[-1].time_ms - uncovered_run[0].time_ms
        if span_ms >= max(1200, preset.target_gap_ms * 2):
            issues.append(
                ValidationIssue(
                    code="TIMING_STRONG_EVENTS_IGNORED",
                    severity="warning",
                    message="A sustained sequence of strong musical events is not represented by nearby objects.",
                    category="timing",
                    start_time_ms=uncovered_run[0].time_ms,
                    end_time_ms=uncovered_run[-1].time_ms,
                    measured_value=float(len(uncovered_run)),
                    allowed_value=2.0,
                    suggestion="Add or retime objects in this section if the density feels too empty.",
                )
            )
        uncovered_run.clear()

    object_times = [item.time for item in beatmap.objects]

    for event in strong_events:
        nearest_delta = min(abs(object_time - event.time_ms) for object_time in object_times) if object_times else None
        if nearest_delta is not None and nearest_delta <= covered_tolerance:
            flush_run()
            continue
        uncovered_run.append(event)

    flush_run()


def _average(values: list[int]) -> float:
    return sum(values) / len(values) if values else 0.0

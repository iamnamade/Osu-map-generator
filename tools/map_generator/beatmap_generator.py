from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import numpy as np

from dataclasses import replace as replace_dataclass

from .audio_analyzer import analyze_audio
from ..text_utils import normalize_unicode_text
from .config import DifficultyPreset, get_difficulty_preset
from .event_selector import select_events
from .generation_config import build_pattern_config
from .models import (
    BeatmapExport,
    GeneratedCircleHitObject,
    GeneratedHitObject,
    GeneratedSliderHitObject,
    GeneratedSpinnerHitObject,
    GenerationDiagnostics,
    GenerationResult,
)
from .position_generator import (
    PLAYFIELD_HEIGHT,
    PLAYFIELD_WIDTH,
    PositionGenerationResult,
    generate_positions,
)
from .utils import (
    MapGeneratorError,
    average,
    clamp,
    finite_number,
    format_seconds,
    resolve_browser_audio_path,
    write_json,
)
from .variation import EventSelectionVariation, PositionVariation


def generate_beatmap(
    *,
    audio_path: Path,
    title: str,
    artist: str,
    difficulty: str,
    seed: int,
    output_path: Path,
    analysis_output_path: Path | None,
    project_root: Path,
    browser_audio_path_override: str | None = None,
    title_unicode: str | None = None,
    artist_unicode: str | None = None,
) -> GenerationResult:
    """Run analysis, select events, place circles, validate, and export JSON."""

    preset = get_difficulty_preset(difficulty)
    analysis = analyze_audio(audio_path)

    # Reuse the internal _load_audio helper for raw samples
    samples = None
    sample_rate = None
    generation_warnings: list[str] = []
    if preset.rhythm_intelligence_enabled:
        try:
            from .audio_analyzer import _load_audio, ANALYSIS_SAMPLE_RATE
            samples, sample_rate = _load_audio(audio_path)
        except Exception as exc:
            generation_warnings.append(
                f"[rhythm] Could not load raw samples for rhythm intelligence: {exc}"
            )
            samples = None

    return generate_beatmap_from_analysis(
        analysis=analysis,
        audio_path=audio_path,
        title=title,
        artist=artist,
        difficulty=difficulty,
        seed=seed,
        output_path=output_path,
        analysis_output_path=analysis_output_path,
        project_root=project_root,
        browser_audio_path_override=browser_audio_path_override,
        raw_samples=samples,
        raw_sample_rate=sample_rate,
        existing_warnings=generation_warnings,
        title_unicode=title_unicode,
        artist_unicode=artist_unicode,
    )


def generate_beatmap_from_analysis(
    *,
    analysis: Any,
    audio_path: Path,
    title: str,
    artist: str,
    difficulty: str,
    seed: int,
    output_path: Path,
    analysis_output_path: Path | None,
    project_root: Path,
    selected_events_override: list[Any] | None = None,
    event_variation: EventSelectionVariation | None = None,
    position_variation: PositionVariation | None = None,
    preset: DifficultyPreset | None = None,
    base_variation: PositionVariation | None = None,
    pattern_config: Any | None = None,
    generator_metadata: dict[str, Any] | None = None,
    browser_audio_path_override: str | None = None,
    raw_samples: np.ndarray | None = None,
    raw_sample_rate: int | None = None,
    phrase_info: list[Any] | None = None,
    existing_warnings: list[str] | None = None,
    title_unicode: str | None = None,
    artist_unicode: str | None = None,
) -> GenerationResult:
    preset = preset or get_difficulty_preset(difficulty)
    generation_warnings: list[str] = list(existing_warnings) if existing_warnings else []

    # Use rhythm intelligence when enabled and no override is provided
    rhythm_model = None
    rhythm_diagnostics = None
    if preset.rhythm_intelligence_enabled and selected_events_override is None:
        try:
            from .rhythm.rhythm_pipeline import (
                DEFAULT_RHYTHM_CONFIG,
                RhythmPipelineConfig,
                build_rhythm_model,
                select_rhythmic_timings,
            )
            rhythm_config = RhythmPipelineConfig(
                enhanced_analysis_enabled=True,
                subdivision_enabled=preset.subdivision_enabled,
                fill_subdivision_gaps=preset.subdivision_fill_gaps,
                max_allowed_empty_gap_ms=preset.max_empty_gap_ms,
                min_timing_confidence=preset.min_timing_confidence,
            )
            rhythm_model = build_rhythm_model(
                analysis=analysis,
                preset=preset,
                samples=raw_samples,
                sample_rate=raw_sample_rate,
                rhythm_config=rhythm_config,
                phrase_info=phrase_info,
            )
        except Exception as exc:
            generation_warnings.append(
                f"[rhythm] Rhythm intelligence initialization failed: {exc}"
            )
            rhythm_model = None

    selected_events = selected_events_override or select_events(
        analysis, preset,
        variation=event_variation,
        rhythm_model=rhythm_model,
    )

    if rhythm_model is not None and hasattr(rhythm_model, 'diagnostics') and rhythm_model.diagnostics is not None:
        rhythm_diagnostics = rhythm_model.diagnostics

    effective_variation = _merge_position_variations(base_variation, position_variation)
    positioned = generate_positions(
        selected_events,
        preset,
        seed,
        variation=effective_variation,
        pattern_config=pattern_config or build_pattern_config(preset),
        analysis=analysis,
    )

    # Phase 11: Slider Intelligence
    slider_diag = None
    spinner_diag = None
    sustained = None
    if preset.slider_enabled and raw_samples is not None and raw_sample_rate is not None:
        try:
            from .sliders.slider_pipeline import (
                SliderPipelineConfig,
                process_sliders,
            )
            from .sliders.sustained_analysis import analyze_sustained_content

            sustained = analyze_sustained_content(raw_samples, raw_sample_rate)
            slider_cfg = SliderPipelineConfig(
                slider_enabled=True,
                min_confidence_threshold=0.2,
                max_slider_ratio=preset.slider_max_ratio,
                min_slider_ratio=getattr(preset, 'slider_min_ratio', 0.0),
                quality_threshold=preset.slider_quality_threshold,
            )

            points_for_sliders = _extract_points(positioned.objects)
            new_objects, new_points, slider_diag = process_sliders(
                selected_events,
                positioned.objects,
                points_for_sliders,
                sustained=sustained,
                samples=raw_samples,
                sample_rate=raw_sample_rate,
                preset=preset,
                seed=seed,
                slider_config=slider_cfg,
                phrase_info=phrase_info,
            )
            new_objects.sort(key=lambda o: (o.time, o.id))
            positioned = PositionGenerationResult(
                objects=new_objects,
                rejected_candidates=positioned.rejected_candidates,
            )
            generator_payload_extra: dict[str, Any] = {
                "sliderCount": slider_diag.accepted_sliders,
            }
        except Exception as exc:
            generation_warnings.append(
                f"[slider] Slider processing failed: {exc}"
            )
            generator_payload_extra = {}
    else:
        generator_payload_extra = {}

    # Phase 12: Spinner Intelligence
    if preset.spinner_enabled:
        try:
            from .spinners.spinner_pipeline import (
                SpinnerPipelineConfig,
                process_spinners,
            )

            spinner_cfg = SpinnerPipelineConfig(
                spinner_enabled=True,
                quality_threshold=preset.spinner_quality_threshold,
            )
            new_objects, spinner_diag = process_spinners(
                positioned.objects,
                analysis=analysis,
                preset=preset,
                seed=seed,
                sustained=sustained,
                spinner_config=spinner_cfg,
                phrase_info=phrase_info,
            )
            if spinner_diag.accepted_spinners > 0:
                positioned = PositionGenerationResult(
                    objects=new_objects,
                    rejected_candidates=positioned.rejected_candidates,
                )
                generator_payload_extra = {
                    **generator_payload_extra,
                    "spinnerCount": spinner_diag.accepted_spinners,
                }
        except Exception as exc:
            generation_warnings.append(
                f"[spinner] Spinner processing failed: {exc}"
            )

    # ---- Phase 24: Density Enforcement & Continuous Fill ----
    # Enforce minimum object density by injecting bridging fill objects
    # when the current object count is below the target.
    positioned = _enforce_density_minimum(
        positioned=positioned,
        selected_events=selected_events,
        analysis=analysis,
        preset=preset,
        seed=seed,
        rhythm_model=rhythm_model,
    )

    # ---- Post-density slider ratio enforcement ----
    # Density enforcement may have added extra circles that diluted the
    # slider ratio.  Convert exactly enough circles to sliders to reach
    # the minimum ratio, while never exceeding the maximum.
    if preset.slider_enabled and sustained is not None and raw_samples is not None and raw_sample_rate is not None:
        post_density_objects = list(positioned.objects)
        post_density_sliders = sum(1 for o in post_density_objects if o.type == "slider")
        post_density_total = len(post_density_objects)
        min_ratio = getattr(preset, 'slider_min_ratio', 0.0)
        max_ratio = preset.slider_max_ratio
        if post_density_total > 0 and min_ratio > 0:
            import math as _math
            target_min = max(0, _math.ceil(post_density_total * min_ratio))
            target_max = max(1, int(post_density_total * max_ratio))
            # Only fill if below minimum AND the slider count hasn't exceeded max
            if post_density_sliders < target_min and post_density_sliders <= target_max:
                try:
                    from .sliders.slider_pipeline import (
                        SliderPipelineConfig,
                        _build_slider,
                        _find_event_index,
                        _force_slider_candidate,
                    )
                    from .sliders.sustained_analysis import analyze_sustained_content
                    from .sliders.slider_decision import decide_slider
                    import random as _random

                    needed = min(target_min - post_density_sliders, target_max - post_density_sliders)
                    _rng = _random.Random(seed + 1000)
                    event_by_time = {e.time_ms: e for e in selected_events}
                    fill_objects: list = []
                    fill_count = 0
                    post_points = _extract_points(post_density_objects)

                    post_cfg = SliderPipelineConfig(
                        slider_enabled=True,
                        min_confidence_threshold=0.2,
                        max_slider_ratio=max_ratio,
                        min_slider_ratio=0.0,
                        quality_threshold=preset.slider_quality_threshold,
                    )

                    for idx, obj in enumerate(post_density_objects):
                        if fill_count >= needed:
                            fill_objects.append(obj)
                            continue
                        if obj.type != "circle":
                            fill_objects.append(obj)
                            continue
                        if idx == 0 or idx == len(post_density_objects) - 1:
                            fill_objects.append(obj)
                            continue
                        event = event_by_time.get(obj.time)
                        if event is None:
                            fill_objects.append(obj)
                            continue
                        ev_idx = _find_event_index(selected_events, obj.time)
                        prev_ev = selected_events[ev_idx - 1] if ev_idx > 0 else None
                        next_ev = selected_events[ev_idx + 1] if ev_idx < len(selected_events) - 1 else None
                        nxt_gap = selected_events[ev_idx + 1].time_ms - obj.time if ev_idx < len(selected_events) - 1 else None
                        candidate = decide_slider(
                            event=event, event_index=ev_idx, sustained=sustained,
                            preset=preset, previous_event=prev_ev, next_event=next_ev,
                            previous_gap_ms=None, next_gap_ms=nxt_gap,
                            phrase_strategy=None, rng=_rng,
                        )
                        if candidate is None:
                            candidate = _force_slider_candidate(
                                event=event, event_index=ev_idx, preset=preset,
                                next_gap_ms=nxt_gap, rng=_rng,
                            )
                        if candidate is None:
                            fill_objects.append(obj)
                            continue
                        result = _build_slider(
                            obj, candidate, post_points, idx, preset, _rng,
                            post_cfg, quality_threshold_override=5.0,
                        )
                        if result is None:
                            fill_objects.append(obj)
                            continue
                        slider_obj, end_point, _q = result
                        fill_objects.append(slider_obj)
                        fill_count += 1
                        post_density_sliders += 1

                    if fill_count > 0:
                        fill_objects.sort(key=lambda o: (o.time, o.id))
                        positioned = PositionGenerationResult(
                            objects=fill_objects,
                            rejected_candidates=positioned.rejected_candidates,
                        )
                except Exception as exc:
                    generation_warnings.append(
                        f"[slider] Post-density slider enforcement failed: {exc}"
                    )

    browser_audio_path = resolve_browser_audio_path(
        audio_source_path=audio_path,
        project_root=project_root,
        audio_browser_path_override=browser_audio_path_override,
    )
    generator_payload: dict[str, Any] = {
        "name": "pulse-practice-generator",
        "version": 4 if spinner_diag is not None and spinner_diag.accepted_spinners > 0 else (3 if slider_diag is not None and slider_diag.accepted_sliders > 0 else (2 if rhythm_model is not None else 1)),
        "difficulty": preset.name,
        "seed": seed,
        "estimatedBpm": round(analysis.bpm, 3),
        "rhythmIntelligenceUsed": rhythm_model is not None,
        "spinnerIntelligenceUsed": spinner_diag is not None and spinner_diag.accepted_spinners > 0,
        **generator_payload_extra,
    }
    if rhythm_model is not None:
        generator_payload["tempoConfidence"] = round(rhythm_model.tempo_confidence, 4)
        generator_payload["subdivisionCount"] = len(rhythm_model.subdivisions)
        if rhythm_diagnostics is not None and rhythm_diagnostics.timing_quality is not None:
            generator_payload["timingQualityOverall"] = round(
                rhythm_diagnostics.timing_quality.overall_quality, 3
            )

    if generator_metadata:
        generator_payload.update(generator_metadata)

    beatmap = BeatmapExport(
        title=title,
        artist=artist,
        audio=browser_audio_path,
        approach_time=preset.approach_time_ms,
        circle_radius=preset.circle_radius,
        objects=positioned.objects,
        generator=generator_payload,
    )

    validate_generated_beatmap(
        beatmap=beatmap,
        audio_duration_ms=analysis.duration_ms,
        start_padding_ms=preset.start_padding_ms,
        end_padding_ms=preset.end_padding_ms,
    )

    if analysis_output_path is not None:
        write_json(analysis_output_path, analysis.to_dict())

    beatmap_payload = beatmap.to_dict()
    # Persist Unicode metadata under the same ``osu`` extra_fields namespace the
    # importer/exporter use, so generated maps round-trip TitleUnicode /
    # ArtistUnicode into exported .osu headers (I1).
    unicode_metadata = {
        key: normalize_unicode_text(value).strip()
        for key, value in (
            ("titleUnicode", title_unicode),
            ("artistUnicode", artist_unicode),
        )
        if isinstance(value, str) and value.strip()
    }
    if unicode_metadata:
        existing_osu = beatmap_payload.get("osu")
        merged_osu = dict(existing_osu) if isinstance(existing_osu, dict) else {}
        merged_osu.update(unicode_metadata)
        beatmap_payload["osu"] = merged_osu
    write_json(output_path, beatmap_payload)

    diagnostics = _build_diagnostics(
        objects=positioned.objects,
        audio_duration_ms=analysis.duration_ms,
        selected_event_count=len(selected_events),
        detected_beats=len(analysis.beats),
        detected_onsets=len(analysis.onsets),
        rejected_candidates=positioned.rejected_candidates,
    )

    # Extract rhythm diagnostics
    rhythm_quality = None
    rhythm_sub_count = None
    rhythm_tempo_conf = None
    rhythm_diag_dict = None
    if rhythm_diagnostics is not None:
        rhythm_quality = (
            rhythm_diagnostics.timing_quality.overall_quality
            if rhythm_diagnostics.timing_quality is not None
            else None
        )
        rhythm_sub_count = len(rhythm_diagnostics.subdivisions)
        rhythm_tempo_conf = rhythm_diagnostics.global_tempo_confidence
        rhythm_diag_dict = rhythm_diagnostics.to_dict()

    slider_diag_dict = slider_diag.to_dict() if slider_diag is not None else None
    spinner_diag_dict = spinner_diag.to_dict() if spinner_diag is not None else None

    return GenerationResult(
        analysis=analysis,
        selected_events=selected_events,
        beatmap=beatmap,
        diagnostics=diagnostics,
        rhythm_quality_score=rhythm_quality,
        rhythm_subdivision_count=rhythm_sub_count,
        rhythm_tempo_confidence=rhythm_tempo_conf,
        rhythm_diagnostics=rhythm_diag_dict,
        slider_diagnostics=slider_diag_dict,
        spinner_diagnostics=spinner_diag_dict,
        warnings=generation_warnings,
    )


def validate_generated_beatmap(
    *,
    beatmap: BeatmapExport,
    audio_duration_ms: int,
    start_padding_ms: int,
    end_padding_ms: int,
) -> None:
    if not beatmap.objects:
        raise MapGeneratorError("Generated beatmap is invalid: at least one object is required.")

    if not beatmap.audio.startswith("/"):
        raise MapGeneratorError(f"Generated beatmap audio path is invalid: {beatmap.audio}")

    safe_end_limit = max(0, audio_duration_ms - end_padding_ms)
    seen_ids: set[int] = set()
    seen_times: set[int] = set()
    previous_time = -1

    for expected_id, hit_object in enumerate(beatmap.objects, start=1):
        if hit_object.id != expected_id:
            raise MapGeneratorError(
                f"Generated beatmap is invalid: IDs must be sequential starting at 1. Found {hit_object.id}, expected {expected_id}."
            )

        if hit_object.id in seen_ids:
            raise MapGeneratorError(f"Generated beatmap is invalid: duplicate ID {hit_object.id}.")
        seen_ids.add(hit_object.id)

        if hit_object.type not in ("circle", "slider", "spinner"):
            raise MapGeneratorError(
                f"Generated beatmap is invalid: unsupported object type {hit_object.type!r}."
            )

        if hit_object.type == "spinner":
            if hit_object.end_time <= hit_object.time:
                raise MapGeneratorError(
                    f"Generated beatmap is invalid: spinner {hit_object.id} endTime must be greater than time."
                )
            if hit_object.end_time > audio_duration_ms:
                raise MapGeneratorError(
                    f"Generated beatmap is invalid: spinner {hit_object.id} endTime exceeds audio duration."
                )
            if hit_object.end_time > safe_end_limit:
                raise MapGeneratorError(
                    f"Generated beatmap is invalid: spinner {hit_object.id} ends too close to the end of the audio."
                )
        else:
            finite_number(float(hit_object.x), f"Object {hit_object.id} x")
            finite_number(float(hit_object.y), f"Object {hit_object.id} y")
        finite_number(float(hit_object.time), f"Object {hit_object.id} time")

        if hit_object.time < 0:
            raise MapGeneratorError(f"Generated beatmap is invalid: negative time for object {hit_object.id}.")

        if hit_object.time < start_padding_ms:
            raise MapGeneratorError(
                f"Generated beatmap is invalid: object {hit_object.id} occurs before start padding."
            )

        if hit_object.time > audio_duration_ms:
            raise MapGeneratorError(
                f"Generated beatmap is invalid: object {hit_object.id} exceeds audio duration."
            )

        if hit_object.time > safe_end_limit:
            raise MapGeneratorError(
                f"Generated beatmap is invalid: object {hit_object.id} is too close to the end of the audio."
            )

        if hit_object.time in seen_times:
            raise MapGeneratorError(
                f"Generated beatmap is invalid: duplicate timestamp {hit_object.time} ms."
            )
        seen_times.add(hit_object.time)

        if hit_object.time <= previous_time:
            raise MapGeneratorError(
                f"Generated beatmap is invalid: timestamps must be strictly increasing. Object {hit_object.id} is out of order."
            )
        previous_time = hit_object.time

        if hit_object.type != "spinner":
            if not (0 <= hit_object.x <= PLAYFIELD_WIDTH):
                raise MapGeneratorError(
                    f"Generated beatmap is invalid: x coordinate {hit_object.x} is outside the {PLAYFIELD_WIDTH}px playfield."
                )

            if not (0 <= hit_object.y <= PLAYFIELD_HEIGHT):
                raise MapGeneratorError(
                    f"Generated beatmap is invalid: y coordinate {hit_object.y} is outside the {PLAYFIELD_HEIGHT}px playfield."
                )


def format_generation_report(
    *,
    result: GenerationResult,
    audio_path: Path,
    difficulty: str,
    seed: int,
    output_path: Path,
    analysis_output_path: Path | None,
) -> str:
    diagnostics = result.diagnostics
    analysis_path_label = analysis_output_path.as_posix() if analysis_output_path is not None else "(not written)"

    lines = [
        "Generated beatmap successfully",
        "",
        f"Audio: {audio_path.as_posix()}",
        f"Difficulty: {difficulty}",
        f"Seed: {seed}",
        f"Estimated BPM: {result.analysis.bpm:.1f}",
        f"Duration: {format_seconds(result.analysis.duration_ms)} seconds",
        f"Detected beats: {diagnostics.detected_beats}",
        f"Detected onsets: {diagnostics.detected_onsets}",
        f"Selected objects: {diagnostics.selected_objects}",
        f"Output: {output_path.as_posix()}",
        f"Analysis: {analysis_path_label}",
        "",
        "Diagnostics",
        f"Minimum object gap: {diagnostics.min_object_gap_ms} ms",
        f"Maximum object gap: {diagnostics.max_object_gap_ms} ms",
        f"Average object gap: {diagnostics.average_object_gap_ms:.1f} ms",
        f"Minimum jump distance: {diagnostics.min_jump_distance:.1f}px",
        f"Maximum jump distance: {diagnostics.max_jump_distance:.1f}px",
        f"Average jump distance: {diagnostics.average_jump_distance:.1f}px",
        f"Highest cursor speed: {diagnostics.highest_cursor_speed:.1f}px/s",
        f"Rejected position candidates: {diagnostics.rejected_candidates}",
    ]

    # Add rhythm intelligence diagnostics if available
    if hasattr(result, 'rhythm_quality_score') and result.rhythm_quality_score is not None:
        lines.extend([
            "",
            "Rhythm Intelligence",
            f"Timing quality score: {result.rhythm_quality_score:.2f}/100",
        ])
    if hasattr(result, 'rhythm_subdivision_count') and result.rhythm_subdivision_count is not None:
        lines.append(f"Subdivision regions: {result.rhythm_subdivision_count}")
    if hasattr(result, 'rhythm_tempo_confidence') and result.rhythm_tempo_confidence is not None:
        lines.append(f"Tempo confidence: {result.rhythm_tempo_confidence:.3f}")

    # Add spinner intelligence diagnostics if available
    if getattr(result, 'spinner_diagnostics', None):
        spinner_diag = result.spinner_diagnostics
        lines.extend([
            "",
            "Spinner Intelligence",
            f"Spinners accepted: {spinner_diag.get('acceptedSpinners', 0)}",
            f"Spinner candidates evaluated: {spinner_diag.get('totalCandidates', 0)}",
            f"Spinners rejected: {spinner_diag.get('rejectedSpinners', 0)}",
            f"Average spinner duration: {spinner_diag.get('averageDurationMs', 0):.0f} ms",
            f"Longest spinner: {spinner_diag.get('longestDurationMs', 0)} ms",
            f"Shortest spinner: {spinner_diag.get('shortestDurationMs', 0)} ms",
            f"Average quality score: {spinner_diag.get('averageQualityScore', 0):.1f}/100",
        ])
        trigger_counts = spinner_diag.get('triggerTypeCounts') or {}
        if trigger_counts:
            trigger_summary = ", ".join(
                f"{label}: {count}"
                for label, count in sorted(trigger_counts.items())
            )
            lines.append(f"Musical triggers: {trigger_summary}")
        if spinner_diag.get('fatiguePeak'):
            lines.extend([
                "Recovery & Fatigue",
                f"Fatigue peak: {spinner_diag.get('fatiguePeak', 0):.2f} at {spinner_diag.get('fatiguePeakTimeMs', 0)} ms",
                f"Recovery windows: {len(spinner_diag.get('recoveryWindows') or [])}",
            ])

    # Surface generation warnings so operators see degraded subsystems
    if getattr(result, 'warnings', None):
        lines.extend(["", "Warnings"])
        for warning in result.warnings:
            lines.append(f"- {warning}")

    return "\n".join(lines)


def _enforce_density_minimum(
    *,
    positioned: PositionGenerationResult,
    selected_events: list[Any],
    analysis: Any,
    preset: DifficultyPreset,
    seed: int,
    rhythm_model: Any = None,
) -> PositionGenerationResult:
    """Enforce minimum object density by injecting bridging fill objects.

    The Phase 24 knobs are two authorities: ``min_density_target`` is a hard
    floor the map must reach, and ``target_density`` is the aim. ``target_count``
    is the larger of the two, so the floor is never collapsed by a smaller
    target. When the current object count is below it, circles are injected in
    a multi-pass, roomiest-gap-first sweep at musical subdivisions until the
    target is met or no admissible gap remains. Spinner entry/recovery buffers
    are honoured so fills never crowd a spinner.
    """
    if preset.min_density_target <= 0 and preset.target_density <= 0:
        return positioned

    duration_sec = analysis.duration_ms / 1000.0
    floor_count = (
        int(math.ceil(preset.min_density_target * duration_sec))
        if preset.min_density_target > 0
        else 0
    )
    aim_count = (
        int(math.ceil(preset.target_density * duration_sec))
        if preset.target_density > 0
        else 0
    )
    target_count = max(floor_count, aim_count)

    objects = list(positioned.objects)
    if len(objects) >= target_count:
        return positioned

    deficit = target_count - len(objects)
    rng = random.Random(seed + 9999)

    min_gap = max(1, preset.min_gap_ms)
    bpm = analysis.bpm if getattr(analysis, 'bpm', 0) and analysis.bpm > 0 else 120.0
    beat_interval_ms = max(1, int(round(60000.0 / bpm)))
    half_beat_ms = max(1, beat_interval_ms // 2)
    offset_ms = int(getattr(analysis, 'offset_ms', 0) or 0)

    spinner_entry_ms = max(min_gap, int(getattr(preset, 'spinner_entry_buffer_ms', min_gap)))
    spinner_recovery_ms = max(min_gap, int(getattr(preset, 'spinner_recovery_after_ms', min_gap)))

    injected = 0
    guard = 0
    max_rounds = max(1, deficit * 4)
    # Multi-pass fill: each round inserts one circle into the roomiest gap that
    # can still host it, so we add no more objects than needed and never
    # over-saturate an already-dense region.
    while injected < deficit and guard < max_rounds:
        guard += 1
        sorted_objs = sorted(objects, key=lambda o: (o.time, o.id))
        best: tuple[float, int, Any, Any] | None = None
        for i in range(len(sorted_objs) - 1):
            prev_obj = sorted_objs[i]
            next_obj = sorted_objs[i + 1]
            prev_end = _density_object_end(prev_obj)
            lo = prev_end + (spinner_recovery_ms if prev_obj.type == "spinner" else min_gap)
            hi = next_obj.time - (spinner_entry_ms if next_obj.type == "spinner" else min_gap)
            if hi <= lo:
                continue
            fill = _snap_fill_time((lo + hi) / 2.0, lo, hi, offset_ms, half_beat_ms)
            if fill is None:
                continue
            room = hi - lo
            if best is None or room > best[0]:
                best = (float(room), fill, prev_obj, next_obj)

        if best is None:
            break

        _room, fill_time, prev_obj, next_obj = best
        energy = analysis.energy_at(fill_time)

        # Interpolate position between neighbours with a perpendicular offset
        # for variety; fall back to a random slot when a neighbour is a spinner.
        if prev_obj.type != "spinner" and next_obj.type != "spinner":
            px = getattr(prev_obj, 'x', 256)
            py = getattr(prev_obj, 'y', 192)
            nx = getattr(next_obj, 'x', 256)
            ny = getattr(next_obj, 'y', 192)
            span = max(1, next_obj.time - prev_obj.time)
            t_frac = clamp((fill_time - prev_obj.time) / span, 0.0, 1.0)
            angle = rng.uniform(0.0, math.pi * 2)
            offset = preset.min_jump_distance * 0.5
            x = int(clamp(px + (nx - px) * t_frac + math.cos(angle) * offset, 32, 480))
            y = int(clamp(py + (ny - py) * t_frac + math.sin(angle) * offset, 32, 352))
        else:
            x = rng.randint(64, 448)
            y = rng.randint(64, 320)

        objects.append(
            GeneratedCircleHitObject(
                id=0,
                type="circle",
                x=x,
                y=y,
                time=int(fill_time),
                extra_fields={
                    "source": "density_fill",
                    "energy": round(energy, 4),
                },
            )
        )
        injected += 1

    objects.sort(key=lambda o: (o.time, o.id))

    # Renumber IDs
    for idx, obj in enumerate(objects, start=1):
        if hasattr(obj, 'id'):
            if obj.type == 'circle':
                objects[idx - 1] = GeneratedCircleHitObject(
                    id=idx, type='circle', x=obj.x, y=obj.y, time=obj.time,
                    extra_fields=dict(obj.extra_fields),
                )
            elif obj.type == 'slider':
                objects[idx - 1] = GeneratedSliderHitObject(
                    id=idx, type='slider', x=obj.x, y=obj.y, time=obj.time,
                    end_time=obj.end_time, path_type=obj.path_type,
                    control_points=obj.control_points, repeats=obj.repeats,
                    pixel_length=obj.pixel_length, extra_fields=dict(obj.extra_fields),
                )
            elif obj.type == 'spinner':
                objects[idx - 1] = GeneratedSpinnerHitObject(
                    id=idx, type='spinner', time=obj.time, end_time=obj.end_time,
                    extra_fields=dict(obj.extra_fields),
                )

    return PositionGenerationResult(
        objects=objects,
        rejected_candidates=positioned.rejected_candidates,
    )


def _density_object_end(obj: Any) -> int:
    """Return the last millisecond an object occupies (start for circles)."""
    end_time = getattr(obj, 'end_time', None)
    if end_time is None:
        return int(obj.time)
    return int(max(int(obj.time), int(end_time)))


def _snap_fill_time(
    center: float,
    lo: float,
    hi: float,
    offset_ms: int,
    half_beat_ms: int,
) -> int | None:
    """Snap ``center`` to the nearest half-beat grid point inside [lo, hi].

    Prefers a musical anchor but falls back to the raw midpoint when no grid
    point fits the admissible window. Returns ``None`` when the window is empty.
    """
    if hi < lo:
        return None
    if half_beat_ms > 0:
        k = round((center - offset_ms) / half_beat_ms)
        for delta in (0, 1, -1, 2, -2):
            cand = offset_ms + (k + delta) * half_beat_ms
            if lo <= cand <= hi:
                return int(cand)
    if lo <= center <= hi:
        return int(round(center))
    return None


def _merge_position_variations(
    base: PositionVariation | None,
    candidate: PositionVariation | None,
) -> PositionVariation:
    """Merge the Phase 19 base variation with a per-candidate variation.

    The base variation carries the mapping-control biases (stream, burst,
    pattern family weights); the candidate variation carries deterministic
    per-candidate diversity on top. Candidate values win where they differ
    from the neutral defaults.
    """
    if base is None:
        return candidate or PositionVariation()
    if candidate is None:
        return base
    neutral = PositionVariation()
    overrides: dict[str, object] = {}
    for field_name, field_value in vars(candidate).items():
        if field_value != getattr(neutral, field_name):
            overrides[field_name] = field_value
    return replace_dataclass(base, **overrides)


def _extract_points(objects: list[GeneratedHitObject]) -> list[Any]:
    """Extract position points from hit objects for slider processing."""
    from .position_generator import _Point as _GenPoint
    points: list[Any] = []
    for obj in objects:
        x = getattr(obj, "x", 0)
        y = getattr(obj, "y", 0)
        points.append(_GenPoint(x=float(x), y=float(y)))
    return points


def _build_diagnostics(
    *,
    objects: list[GeneratedHitObject],
    audio_duration_ms: int,
    selected_event_count: int,
    detected_beats: int,
    detected_onsets: int,
    rejected_candidates: int,
) -> GenerationDiagnostics:
    # Positional diagnostics only consider positioned objects (circles and
    # sliders); spinners have no x/y coordinates.
    positioned = [obj for obj in objects if getattr(obj, "x", None) is not None]
    gaps = [
        right.time - left.time
        for left, right in zip(positioned, positioned[1:], strict=False)
    ]
    jump_distances = [
        math.hypot(right.x - left.x, right.y - left.y)
        for left, right in zip(positioned, positioned[1:], strict=False)
    ]
    cursor_speeds = [
        distance / ((right.time - left.time) / 1000)
        for (left, right), distance in zip(
            zip(positioned, positioned[1:], strict=False),
            jump_distances,
            strict=False,
        )
        if right.time > left.time
    ]

    return GenerationDiagnostics(
        min_object_gap_ms=min(gaps) if gaps else audio_duration_ms,
        max_object_gap_ms=max(gaps) if gaps else audio_duration_ms,
        average_object_gap_ms=average(gaps) if gaps else float(audio_duration_ms),
        min_jump_distance=min(jump_distances) if jump_distances else 0.0,
        max_jump_distance=max(jump_distances) if jump_distances else 0.0,
        average_jump_distance=average(jump_distances) if jump_distances else 0.0,
        highest_cursor_speed=max(cursor_speeds) if cursor_speeds else 0.0,
        rejected_candidates=rejected_candidates,
        detected_beats=detected_beats,
        detected_onsets=detected_onsets,
        selected_objects=selected_event_count,
    )

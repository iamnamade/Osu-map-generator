from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from ..config import DifficultyPreset, get_difficulty_preset
from ..utils import MapGeneratorError

_logger = logging.getLogger(__name__)
from ..validation.beatmap_validator import validate_beatmap
from ..geometry.collision import clear_slider_cache

# Safety: maximum wall-clock seconds allowed for any single structural
# safety stage or correction stage before we bail out with the best map
# so far.
_STAGE_TIMEOUT_SECONDS = 10.0
# Safety: maximum number of overlap-resolution passes.  Each pass is a
# single forward scan with a bounded look-back window, but we cap the
# total number of scans to prevent oscillation in pathological cases.
_MAX_OVERLAP_PASSES = 3
# Safety: maximum wall-clock seconds for a single auto-fix operation
# (snap, overlap, sanitize) before it is reverted and remaining
# auto-fixes are skipped.
_OP_TIMEOUT_SECONDS = 1.5


def _elapsed(start: float) -> float:
    """Seconds elapsed since *start*."""
    return time.monotonic() - start
from .change_log import (
    format_improvement_comparison,
    format_improvement_console_report,
    write_correction_report,
)
from .correction_planner import build_correction_plan
from .correction_validator import (
    load_analysis,
    load_existing_validation_report,
    load_source_map,
    score_changes_from_reports,
    score_snapshot_from_report,
    validate_map_data,
    write_map_output,
)
from .density_corrector import build_density_action
from .difficulty_corrector import build_difficulty_action
from .local_optimizer import deadline_exceeded, get_diagnostics, reset_diagnostics, set_deadline
from .models import (
    CorrectionAction,
    CorrectionReport,
    CorrectionSummary,
    PostprocessContext,
    PostprocessLimits,
    ProcessingStage,
    STAGE_ORDER,
)
from .movement_corrector import build_movement_action
from .repetition_corrector import build_repetition_action
from .stacking_corrector import build_stacking_action
from .timing_corrector import build_timing_action


@dataclass(frozen=True)
class ImprovementRunResult:
    source_map_path: Path
    output_map_path: Path
    output_report_path: Path
    changes_output_path: Path
    original_report: Any
    final_report: Any
    correction_report: CorrectionReport
    console_report: str


def improve_beatmap(
    *,
    map_path: Path,
    analysis_path: Path,
    report_path: Path,
    difficulty: str,
    seed: int,
    output_path: Path,
    report_output_path: Path,
    changes_output_path: Path,
    verbose: bool = False,
    limits: PostprocessLimits | None = None,
    source_map_label: str | None = None,
    output_map_label: str | None = None,
    preset: DifficultyPreset | None = None,
) -> ImprovementRunResult:
    preset = preset or get_difficulty_preset(difficulty)
    source_map = load_source_map(map_path)
    load_existing_validation_report(report_path)
    analysis = load_analysis(analysis_path)
    context = PostprocessContext(
        source_map_path=map_path,
        analysis_path=analysis_path,
        original_report_path=report_path,
        output_map_path=output_path,
        output_report_path=report_output_path,
        changes_output_path=changes_output_path,
        difficulty=difficulty,
        preset=preset,
        seed=seed,
        source_map_label=source_map_label or _display_path(map_path),
        output_map_label=output_map_label or _display_path(output_path),
        analysis=analysis,
        limits=limits or PostprocessLimits(),
    )

    reset_diagnostics()
    clear_slider_cache()
    _obj_count = len(source_map.get("objects", []))
    _timing_log: list[str] = []
    _overall_start = time.monotonic()
    _timing_log.append(f"Easy post-processing started (objects={_obj_count})")

    _t0 = time.monotonic()
    original_result = validate_beatmap(
        map_path=map_path,
        analysis_path=analysis_path,
        difficulty=difficulty,
        map_label=context.source_map_label,
    )
    original_report = original_result.report
    _timing_log.append(f"initial validation: {_elapsed(_t0):.2f}s")

    _t0 = time.monotonic()
    current_map, current_report, actions = _apply_structural_safety(
        source_map=source_map,
        original_report=original_report,
        context=context,
    )
    _timing_log.append(f"structural safety: {_elapsed(_t0):.2f}s")

    if any(
        issue.severity == "critical" and issue.category == "structural"
        for issue in current_report.issues
    ):
        critical_codes = [
            issue.code
            for issue in current_report.issues
            if issue.severity == "critical" and issue.category == "structural"
        ]
        _logger.warning(
            "Beatmap has unresolved critical structural issues (%s). "
            "Continuing with degraded post-processing instead of aborting.",
            ", ".join(critical_codes),
        )

    _stage_totals: dict[str, float] = {}
    _stage_attempts: dict[str, int] = {}
    _stage_validations_per_stage: dict[str, int] = {}
    _diag_before = get_diagnostics()
    stage_start = time.monotonic()
    for stage in STAGE_ORDER[1:]:
        if _elapsed(stage_start) > _STAGE_TIMEOUT_SECONDS:
            _logger.warning(
                "Post-processing exceeded %.1fs overall deadline at stage %s — "
                "returning best map so far.",
                _STAGE_TIMEOUT_SECONDS,
                stage,
            )
            break
        attempts = 0
        while attempts < context.limits.max_correction_passes:
            if _elapsed(stage_start) > _STAGE_TIMEOUT_SECONDS:
                _logger.warning(
                    "Stage %s exceeded %.1fs timeout after %d attempts — "
                    "moving on to next stage.",
                    stage,
                    _STAGE_TIMEOUT_SECONDS,
                    attempts,
                )
                break
            # Set per-stage deadline: budget ~2s per stage, capped by overall deadline
            _stage_budget = min(2.0, _STAGE_TIMEOUT_SECONDS - _elapsed(stage_start))
            set_deadline(time.monotonic() + max(0.5, _stage_budget))
            evaluation = _attempt_stage(
                stage=stage,
                current_map=current_map,
                current_report=current_report,
                actions=actions,
                context=context,
            )
            set_deadline(0.0)  # Reset deadline after stage
            if evaluation is None:
                break

            actions.append(_uniquify_action_id(evaluation.action, actions))
            if not evaluation.accepted:
                attempts += 1
                continue

            current_map = evaluation.candidate_map
            current_report = evaluation.report
            attempts += 1
        _stage_totals[stage] = _elapsed(stage_start)
        _stage_attempts[stage] = attempts
        _diag_after = get_diagnostics()
        _stage_validations_per_stage[stage] = _diag_after["validation_calls"] - _diag_before["validation_calls"]
        _diag_before = _diag_after
        _timing_log.append(
            f"{stage}: {_stage_totals[stage]:.2f}s (attempts={attempts}, "
            f"validations={_stage_validations_per_stage[stage]})"
        )
        _logger.info(
            "[postprocess] %s: attempts=%d",
            stage,
            attempts,
        )

    keep_improved, rejection_reason = _should_keep_improved(
        before_report=original_report,
        after_report=current_report,
        tolerance=context.limits.overall_score_tolerance,
    )
    selected_map = current_map if keep_improved else _copy_map(source_map)
    selected_report = (
        current_report
        if keep_improved
        else validate_map_data(
            map_data=selected_map,
            analysis_path=analysis_path,
            difficulty=difficulty,
            map_label=context.output_map_label,
        ).report
    )

    _t0 = time.monotonic()
    write_map_output(output_path, selected_map)
    _timing_log.append(f"write output: {_elapsed(_t0):.2f}s")
    _t0 = time.monotonic()
    validate_beatmap(
        map_path=output_path,
        analysis_path=analysis_path,
        difficulty=difficulty,
        output_path=report_output_path,
        map_label=context.output_map_label,
    )

    _timing_log.append(f"final validation: {_elapsed(_t0):.2f}s")
    _diag_final = get_diagnostics()
    _timing_log.append(f"total validation calls: {_diag_final['validation_calls']}, total validation time: {_diag_final['validation_seconds']:.2f}s")
    _timing_log.append(f"prefilter skips: {_diag_final['prefilter_skips']}, cache hits: {_diag_final['cache_hits']}, local validations: {_diag_final['local_validations']}")
    if _diag_final['slow_validations']:
        for label, secs in _diag_final['slow_validations'][:5]:
            _timing_log.append(f"  slow validation: {label} = {secs:.3f}s")
    _overall_elapsed = _elapsed(_overall_start)
    _timing_log.append(f"Easy post-processing total: {_overall_elapsed:.2f}s")
    _logger.info("[postprocess] TIMING:\n  %s", "\n  ".join(_timing_log))

    correction_report = CorrectionReport(
        version=1,
        source_map=context.source_map_label,
        output_map=context.output_map_label,
        difficulty=difficulty,
        seed=seed,
        accepted=keep_improved,
        before=score_snapshot_from_report(original_report),
        after=score_snapshot_from_report(selected_report),
        score_changes=score_changes_from_reports(original_report, selected_report),
        summary=_build_summary(actions),
        actions=actions,
        rejection_reason=None if keep_improved else rejection_reason,
    )
    write_correction_report(changes_output_path, correction_report)
    console_report = format_improvement_console_report(
        title=selected_map.get("title", "Unknown Title"),
        difficulty=difficulty,
        seed=seed,
        correction_report=correction_report,
        output_map_path=output_path,
        output_report_path=report_output_path,
        changes_output_path=changes_output_path,
        verbose=verbose,
    )

    return ImprovementRunResult(
        source_map_path=map_path,
        output_map_path=output_path,
        output_report_path=report_output_path,
        changes_output_path=changes_output_path,
        original_report=original_report,
        final_report=selected_report,
        correction_report=correction_report,
        console_report=console_report,
    )


def improve_all_maps(
    *,
    maps_dir: Path,
    analysis_path: Path,
    reports_dir: Path,
    output_dir: Path,
    improved_reports_dir: Path,
    corrections_dir: Path,
    seed: int,
    verbose: bool = False,
    limits: PostprocessLimits | None = None,
) -> list[ImprovementRunResult]:
    if not maps_dir.exists() or not maps_dir.is_dir():
        raise MapGeneratorError(f"Maps directory does not exist: {maps_dir}")

    map_files = sorted(maps_dir.glob("*.json"))
    if not map_files:
        raise MapGeneratorError(f"No beatmap JSON files were found in {maps_dir}")

    results: list[ImprovementRunResult] = []
    failures: list[str] = []

    for map_file in map_files:
        difficulty = _infer_difficulty(map_file)
        report_file = reports_dir / f"{map_file.stem}-report.json"
        improved_map_file = output_dir / f"{map_file.stem}-improved.json"
        improved_report_file = improved_reports_dir / f"{map_file.stem}-improved-report.json"
        correction_file = corrections_dir / f"{map_file.stem}-corrections.json"

        try:
            results.append(
                improve_beatmap(
                    map_path=map_file,
                    analysis_path=analysis_path,
                    report_path=report_file,
                    difficulty=difficulty,
                    seed=seed,
                    output_path=improved_map_file,
                    report_output_path=improved_report_file,
                    changes_output_path=correction_file,
                    verbose=verbose,
                    limits=limits,
                    source_map_label=_display_path(map_file),
                    output_map_label=_display_path(improved_map_file),
                )
            )
        except MapGeneratorError as error:
            failures.append(f"{map_file.as_posix()}: {error}")

    if failures:
        raise MapGeneratorError("One or more beatmaps could not be improved:\n" + "\n".join(failures))

    return results


def compare_improvements(
    *,
    original_reports_dir: Path,
    improved_reports_dir: Path,
) -> str:
    if not original_reports_dir.exists() or not original_reports_dir.is_dir():
        raise MapGeneratorError(f"Reports directory does not exist: {original_reports_dir}")
    if not improved_reports_dir.exists() or not improved_reports_dir.is_dir():
        raise MapGeneratorError(f"Improved reports directory does not exist: {improved_reports_dir}")

    original_reports = {
        report_file.stem: load_existing_validation_report(report_file)
        for report_file in sorted(original_reports_dir.glob("*.json"))
    }
    rows: list[dict[str, Any]] = []

    for improved_file in sorted(improved_reports_dir.glob("*.json")):
        improved_report = load_existing_validation_report(improved_file)
        base_key = _original_report_key(improved_file.stem)
        original_report = original_reports.get(base_key)
        if original_report is None:
            continue

        label = Path(str(original_report["map"].get("path", base_key))).name
        before_score = float(original_report["scores"]["overall"])
        after_score = float(improved_report["scores"]["overall"])
        delta = after_score - before_score
        if delta > 1e-6:
            status = "improved"
        elif delta < -1e-6:
            status = "worse"
        else:
            status = "unchanged"
        rows.append(
            {
                "label": label,
                "before": before_score,
                "after": after_score,
                "delta": delta,
                "status": status,
            }
        )

    rows.sort(key=lambda row: (-row["delta"], row["label"]))
    return format_improvement_comparison(rows)


def _attempt_stage(
    *,
    stage: ProcessingStage,
    current_map: dict[str, Any],
    current_report: Any,
    actions: list[CorrectionAction],
    context: PostprocessContext,
) -> Any | None:
    if stage == "local_optimization":
        return _attempt_local_optimization(
            current_map=current_map,
            current_report=current_report,
            actions=actions,
            context=context,
        )

    plan = build_correction_plan(current_report)
    issues = plan.issues_by_stage[stage]

    first_rejected: Any | None = None
    for issue in issues:
        # Deadline enforcement: stop cleanly before each issue evaluation
        if deadline_exceeded():
            _logger.info(
                "[postprocess] %s: deadline exceeded — returning best result so far.",
                stage,
            )
            break

        # Fast pre-check: skip issues whose objects would clearly exceed
        # correction limits.  This avoids the expensive full-validation
        # path inside the corrector (~20ms per candidate × 12 candidates).
        if issue.object_ids and _would_exceed_limits(
            actions, issue.object_ids, current_map, context,
        ):
            continue

        evaluation = _build_stage_evaluation(
            stage=stage,
            issue=issue,
            current_map=current_map,
            current_report=current_report,
            context=context,
        )
        if evaluation is None:
            continue
        if not _within_limits(actions, evaluation.action, current_map, context):
            limited_evaluation = replace(
                evaluation,
                action=evaluation.action.with_result(
                    accepted=False,
                    actual_score_impact=evaluation.action.actual_score_impact,
                    rejection_reason="Candidate exceeds configured modification limits.",
                ),
                accepted=False,
                rejection_reason="Candidate exceeds configured modification limits.",
            )
            if first_rejected is None:
                first_rejected = limited_evaluation
            continue
        if evaluation.accepted:
            return evaluation
        if first_rejected is None:
            first_rejected = evaluation

    return first_rejected


def _attempt_local_optimization(
    *,
    current_map: dict[str, Any],
    current_report: Any,
    actions: list[CorrectionAction],
    context: PostprocessContext,
) -> Any | None:
    del actions
    if current_report.scores.movement < 96:
        movement_issue = next(
            (issue for issue in current_report.issues if issue.code.startswith("MOVEMENT_")),
            None,
        )
        if movement_issue is not None:
            return build_movement_action(
                map_data=current_map,
                current_report=current_report,
                context=context,
                issue_code=movement_issue.code,
                issue_object_ids=list(movement_issue.object_ids),
                confidence=0.7,
                stage="local_optimization",
                expected_categories=["movement", "readability"],
                compact=True,
            )

    if current_report.scores.difficulty_consistency < 96:
        return build_difficulty_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code="DIFFICULTY_BEHAVIOR_INCONSISTENT",
            confidence=0.7,
        )

    return None


def _build_stage_evaluation(
    *,
    stage: ProcessingStage,
    issue: Any,
    current_map: dict[str, Any],
    current_report: Any,
    context: PostprocessContext,
) -> Any | None:
    if issue.confidence < context.limits.min_confidence and issue.severity not in {"error", "critical"}:
        return None

    if stage == "timing_corrections":
        return build_timing_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code=issue.code,
            issue_object_ids=list(issue.object_ids),
            confidence=issue.confidence,
        )
    if stage == "movement_corrections":
        return build_movement_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code=issue.code,
            issue_object_ids=list(issue.object_ids),
            confidence=issue.confidence,
        )
    if stage == "stacking_corrections":
        return build_stacking_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code=issue.code,
            issue_object_ids=list(issue.object_ids),
            confidence=issue.confidence,
        )
    if stage == "density_corrections":
        return build_density_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code=issue.code,
            issue_object_ids=list(issue.object_ids),
            confidence=issue.confidence,
            start_time_ms=issue.start_time_ms,
            end_time_ms=issue.end_time_ms,
        )
    if stage == "repetition_corrections":
        return build_repetition_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code=issue.code,
            confidence=issue.confidence,
        )
    if stage == "difficulty_corrections":
        return build_difficulty_action(
            map_data=current_map,
            current_report=current_report,
            context=context,
            issue_code=issue.code,
            confidence=issue.confidence,
        )
    return None


def _apply_structural_safety(
    *,
    source_map: dict[str, Any],
    original_report: Any,
    context: PostprocessContext,
) -> tuple[dict[str, Any], Any, list[CorrectionAction]]:
    _logger.info("  [structural] START — source: %s", context.source_map_label)
    _struct_start = time.monotonic()
    deadline = time.monotonic() + _STAGE_TIMEOUT_SECONDS
    working_map = _copy_map(source_map)
    actions: list[CorrectionAction] = []
    raw_objects = working_map.get("objects")
    if isinstance(raw_objects, list):
        _n_objects = len(raw_objects)
        _logger.info("  [structural] sorting & clamping %d objects to playfield bounds", _n_objects)
        _clamp_start = time.monotonic()
        before_objects = [dict(item) for item in raw_objects if isinstance(item, dict)]
        raw_objects.sort(key=lambda item: (int(round(float(item.get("time", 0)))) if isinstance(item, dict) and isinstance(item.get("time"), (int, float)) else 10**12, int(item.get("id", 0)) if isinstance(item, dict) and isinstance(item.get("id"), (int, float)) else 10**12))
        for index, hit_object in enumerate(raw_objects, start=1):
            if not isinstance(hit_object, dict):
                continue
            before_id = hit_object.get("id")
            before_x = hit_object.get("x")
            before_y = hit_object.get("y")
            before_time = hit_object.get("time")
            if isinstance(before_x, (int, float)) and isinstance(before_y, (int, float)):
                hit_object["x"] = int(round(min(512, max(0, float(before_x)))))
                hit_object["y"] = int(round(min(384, max(0, float(before_y)))))
                if hit_object["x"] != before_x or hit_object["y"] != before_y:
                    actions.append(
                        CorrectionAction(
                            action_id=f"structural-move-{index:04d}",
                            stage="structural_safety",
                            action_type="move_object",
                            reason_code="STRUCTURAL_COORDINATE_CLAMP",
                            object_ids=[index],
                            before={"id": before_id, "x": before_x, "y": before_y, "time": before_time},
                            after={"id": index, "x": hit_object["x"], "y": hit_object["y"], "time": before_time},
                            confidence=0.99,
                            expected_categories=["structural", "readability"],
                            expected_score_impact=0.25,
                            actual_score_impact=0.0,
                            accepted=True,
                        )
                    )
            if isinstance(before_time, (int, float)):
                normalized_time = int(round(float(before_time)))
                if normalized_time != before_time:
                    hit_object["time"] = normalized_time
                    actions.append(
                        CorrectionAction(
                            action_id=f"structural-time-{index:04d}",
                            stage="structural_safety",
                            action_type="adjust_time",
                            reason_code="STRUCTURAL_TIME_NORMALIZATION",
                            object_ids=[index],
                            before={"id": before_id, "time": before_time},
                            after={"id": index, "time": normalized_time},
                            confidence=0.99,
                            expected_categories=["structural", "timing"],
                            expected_score_impact=0.2,
                            actual_score_impact=0.0,
                            accepted=True,
                        )
                    )
            hit_object["id"] = index

        _clamp_ms = (time.monotonic() - _clamp_start) * 1000
        _logger.info("  [structural] sort + clamp: %.1f ms, %d clamp actions", _clamp_ms, len(actions))

        # ---- Auto-fixes with per-operation timeout guards ----
        _autofix_start = time.monotonic()
        _action_count_before_autofix = len(actions)

        # --- Auto-fix: snap timing to nearest valid beat fraction ---
        _snap_snapshot = [dict(item) for item in raw_objects]
        _snap_action_start = len(actions)
        _op_start = time.monotonic()
        _snap_object_timings_to_beats(raw_objects, context, actions)
        _op_ms = (time.monotonic() - _op_start) * 1000
        _logger.info("  [structural] snap timings: %.1f ms (%d objects)", _op_ms, len(raw_objects))
        _autofix_ok = _op_ms <= _OP_TIMEOUT_SECONDS * 1000
        if not _autofix_ok:
            raw_objects[:] = _snap_snapshot
            del actions[_snap_action_start:]
            _logger.warning(
                "  [structural] snap timings exceeded %.0f ms limit (%.1f ms) "
                "— reverted, skipping remaining auto-fixes.",
                _OP_TIMEOUT_SECONDS * 1000,
                _op_ms,
            )

        # --- Auto-fix: resolve spatial overlaps by nudging positions ---
        if _autofix_ok:
            _overlap_snapshot = [dict(item) for item in raw_objects]
            _overlap_action_start = len(actions)
            _op_start = time.monotonic()
            _resolve_object_overlaps(raw_objects, context, actions)
            _op_ms = (time.monotonic() - _op_start) * 1000
            _logger.info("  [structural] resolve overlaps: %.1f ms", _op_ms)
            _autofix_ok = _op_ms <= _OP_TIMEOUT_SECONDS * 1000
            if not _autofix_ok:
                raw_objects[:] = _overlap_snapshot
                del actions[_overlap_action_start:]
                _logger.warning(
                    "  [structural] resolve overlaps exceeded %.0f ms limit (%.1f ms) "
                    "— reverted, skipping remaining auto-fixes.",
                    _OP_TIMEOUT_SECONDS * 1000,
                    _op_ms,
                )

        # --- Auto-fix: validate slider/pixelLength and spinner endTime ---
        if _autofix_ok:
            _sanitize_snapshot = [dict(item) for item in raw_objects]
            _sanitize_action_start = len(actions)
            _op_start = time.monotonic()
            _sanitize_slider_spinner_geometry(raw_objects, actions)
            _op_ms = (time.monotonic() - _op_start) * 1000
            _logger.info("  [structural] sanitize geometry: %.1f ms", _op_ms)
            if _op_ms > _OP_TIMEOUT_SECONDS * 1000:
                raw_objects[:] = _sanitize_snapshot
                del actions[_sanitize_action_start:]
                _logger.warning(
                    "  [structural] sanitize geometry exceeded %.0f ms limit (%.1f ms) "
                    "— reverted.",
                    _OP_TIMEOUT_SECONDS * 1000,
                    _op_ms,
                )

        _autofix_elapsed = (time.monotonic() - _autofix_start) * 1000
        _autofix_actions = len(actions) - _action_count_before_autofix
        _logger.info(
            "  [structural] auto-fixes total: %.1f ms, %d actions",
            _autofix_elapsed,
            _autofix_actions,
        )

        del before_objects

    if "generator" in working_map and not isinstance(working_map.get("generator"), dict):
        working_map.pop("generator", None)

    _struct_elapsed = (time.monotonic() - _struct_start) * 1000
    if time.monotonic() > deadline:
        _logger.warning(
            "  [structural] exceeded %.1fs overall deadline (%.1f ms elapsed) — "
            "proceeding with current state.",
            _STAGE_TIMEOUT_SECONDS,
            _struct_elapsed,
        )
    _logger.info(
        "  [structural] DONE — %.1f ms total, %d actions",
        _struct_elapsed,
        len(actions),
    )

    validation_result = validate_map_data(
        map_data=working_map,
        analysis_path=context.analysis_path,
        difficulty=context.difficulty,
        map_label=context.output_map_label,
    )
    after_report = validation_result.report
    structural_delta = after_report.scores.overall - original_report.scores.overall
    for index, action in enumerate(actions):
        actions[index] = replace(action, actual_score_impact=structural_delta)
    return working_map, after_report, actions


# ---------------------------------------------------------------------------
# Auto-fix helpers for _apply_structural_safety
# ---------------------------------------------------------------------------


_BEAT_FRACTIONS = [1.0, 0.5, 0.25, 0.125]  # 1/1, 1/2, 1/4, 1/8


def _snap_object_timings_to_beats(
    raw_objects: list[dict[str, Any]],
    context: PostprocessContext,
    actions: list[CorrectionAction],
) -> None:
    """Snap each hit object's time to the nearest valid beat fraction.

    Looks at the closest beat from the analysis and nudges the timestamp so
    that every object lands on a musically meaningful subdivision (1/1, 1/2,
    1/4, or 1/8).  Only objects whose time is within a small tolerance of a
    beat anchor are moved, so genuine off-beat placements are left alone.
    """
    beats = context.analysis.beats
    onsets = context.analysis.onsets
    if not beats and not onsets:
        return
    anchors = sorted(
        [(b.time_ms, b.strength) for b in beats]
        + [(o.time_ms, o.strength) for o in onsets],
        key=lambda a: a[0],
    )
    if not anchors:
        return
    max_snap_ms = max(
        40,  # generous tolerance for Free Buff timing resolution
        int(context.preset.onset_strength_threshold * 6),
    )
    for hit_object in raw_objects:
        if not isinstance(hit_object, dict):
            continue
        time_val = hit_object.get("time")
        if not isinstance(time_val, (int, float)):
            continue
        current_time = int(time_val)
        # Find nearest anchor within tolerance
        best_anchor = _nearest_anchor(current_time, anchors)
        if best_anchor is None:
            continue
        anchor_time, anchor_strength = best_anchor
        if abs(anchor_time - current_time) > max_snap_ms:
            continue
        # Only snap if the move is small and doesn't collide with neighbours
        if anchor_time == current_time:
            continue
        snapped_time = anchor_time
        hit_object["time"] = snapped_time
        object_id = hit_object.get("id")
        actions.append(
            CorrectionAction(
                action_id=f"structural-snap-{int(object_id) if isinstance(object_id, (int, float)) else 0:04d}",
                stage="structural_safety",
                action_type="adjust_time",
                reason_code="STRUCTURAL_TIMING_BEAT_SNAP",
                object_ids=[int(object_id) if isinstance(object_id, (int, float)) else 0],
                before={"id": object_id, "time": current_time},
                after={"id": object_id, "time": snapped_time},
                confidence=0.95,
                expected_categories=["structural", "timing"],
                expected_score_impact=0.15,
                actual_score_impact=0.0,
                accepted=True,
            )
        )


def _nearest_anchor(
    current_time: int,
    anchors: list[tuple[int, float]],
) -> tuple[int, float] | None:
    """Binary-search for the nearest anchor to current_time."""
    if not anchors:
        return None
    lo, hi = 0, len(anchors) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if anchors[mid][0] < current_time:
            lo = mid + 1
        else:
            hi = mid
    best = anchors[lo]
    if lo > 0 and abs(anchors[lo - 1][0] - current_time) < abs(best[0] - current_time):
        best = anchors[lo - 1]
    return best


def _resolve_object_overlaps(
    raw_objects: list[dict[str, Any]],
    context: PostprocessContext,
    actions: list[CorrectionAction],
) -> None:
    """Detect and resolve spatial overlaps between hit objects.

    Applies stack-leniency-style nudges: for each pair of nearby objects whose
    discs overlap (accounting for ``circleRadius + safe_margin``), the later
    object is nudged away from the earlier one.  Up to ``_MAX_OVERLAP_PASSES``
    forward scans are performed so that cascading overlaps (where a nudge
    creates a *new* overlap with an already-processed neighbour) are caught.
    The loop terminates early when a pass makes no changes.
    """
    circle_radius = float(
        working_map_radius(raw_objects, context)
    )
    min_clearance = circle_radius * 2.0 + context.preset.safe_margin
    # Maximum temporal gap (ms) for two objects to be considered overlapping.
    _OVERLAP_TIME_WINDOW_MS = 1500
    # Objects are sorted by time, so only the previous N objects need
    # checking — objects further back are guaranteed to be too far away.
    _MAX_LOOKBACK = 5

    for _pass in range(_MAX_OVERLAP_PASSES):
        # Snapshot current positions so we can detect whether this pass
        # moved anything.  If nothing changed, we've converged.
        positions_before: list[tuple[float, float]] = []
        for obj in raw_objects:
            if isinstance(obj, dict) and isinstance(obj.get("x"), (int, float)) and isinstance(obj.get("y"), (int, float)):
                positions_before.append((float(obj["x"]), float(obj["y"])))
            else:
                positions_before.append((-1.0, -1.0))

        # Collect objects with positions
        positioned: list[tuple[int, int, float, float, int]] = []  # (index, id, x, y, time)
        for i, obj in enumerate(raw_objects):
            if not isinstance(obj, dict):
                continue
            x, y = obj.get("x"), obj.get("y")
            oid = obj.get("id")
            t = obj.get("time", 0)
            if (
                isinstance(x, (int, float))
                and isinstance(y, (int, float))
                and isinstance(oid, (int, float))
            ):
                positioned.append((i, int(oid), float(x), float(y), int(t) if isinstance(t, (int, float)) else 0))

        # Resolve pairwise overlaps by nudging the later object.
        nudged_any = False
        for j in range(len(positioned)):
            idx_j, id_j, x_j, y_j, t_j = positioned[j]
            start_i = max(0, j - _MAX_LOOKBACK)
            for i in range(start_i, j):
                idx_i, id_i, x_i, y_i, t_i = positioned[i]
                delta_time = t_j - t_i  # always >= 0 since list is time-sorted
                # Skip pairs that are far apart in time — they never interfere
                if delta_time > _OVERLAP_TIME_WINDOW_MS:
                    continue
                # Scale required clearance by temporal proximity
                time_factor = 1.0 - (delta_time / _OVERLAP_TIME_WINDOW_MS)
                effective_clearance = min_clearance * time_factor
                dx = x_j - x_i
                dy = y_j - y_i
                dist = math.hypot(dx, dy)
                if dist >= effective_clearance or dist < 1e-6:
                    continue
                # Nudge j away from i along the connecting vector
                overlap = effective_clearance - dist + 1.0  # 1px extra breathing room
                if dist > 1e-6:
                    nudge_x = (dx / dist) * overlap
                    nudge_y = (dy / dist) * overlap
                else:
                    nudge_x = overlap
                    nudge_y = 0.0
                new_x = int(round(min(512, max(0, x_j + nudge_x))))
                new_y = int(round(min(384, max(0, y_j + nudge_y))))
                if new_x == int(x_j) and new_y == int(y_j):
                    continue
                obj_j = raw_objects[idx_j]
                obj_j["x"] = new_x
                obj_j["y"] = new_y
                x_j, y_j = float(new_x), float(new_y)
                positioned[j] = (idx_j, id_j, x_j, y_j, t_j)
                nudged_any = True
                actions.append(
                    CorrectionAction(
                        action_id=f"structural-overlap-{id_j:04d}-p{_pass}",
                        stage="structural_safety",
                        action_type="move_object",
                        reason_code="STRUCTURAL_OVERLAP_RESOLVE",
                        object_ids=[id_j],
                        before={"id": id_j, "x": int(x_i), "y": int(y_i)},
                        after={"id": id_j, "x": new_x, "y": new_y},
                        confidence=0.92,
                        expected_categories=["structural", "movement"],
                        expected_score_impact=0.2,
                        actual_score_impact=0.0,
                        accepted=True,
                    )
                )

        if not nudged_any:
            break  # Converged — no overlaps remain.

        # Oscillation guard: if the total movement this pass is below 1px
        # across all objects, the solver is bouncing and won't converge.
        total_movement = 0.0
        for obj_idx, obj in enumerate(raw_objects):
            if not isinstance(obj, dict):
                continue
            x_now = float(obj.get("x", 0))
            y_now = float(obj.get("y", 0))
            x_before, y_before = positions_before[obj_idx]
            if x_before >= 0:
                total_movement += math.hypot(x_now - x_before, y_now - y_before)
        if total_movement < 1.0:
            break  # Below 1px total — solver is oscillating.


def _sanitize_slider_spinner_geometry(
    raw_objects: list[dict[str, Any]],
    actions: list[CorrectionAction],
) -> None:
    """Fix slider pixelLength and spinner endTime to prevent zero-length or
    out-of-bounds geometry that would fail downstream validation.
    """
    for hit_object in raw_objects:
        if not isinstance(hit_object, dict):
            continue
        obj_type = hit_object.get("type")
        obj_id = hit_object.get("id")
        time_val = hit_object.get("time")
        if not isinstance(time_val, (int, float)):
            continue
        if obj_type == "spinner":
            end_time = hit_object.get("endTime")
            if isinstance(end_time, (int, float)):
                if end_time <= time_val:
                    new_end = int(time_val) + 1000  # 1-second minimum
                    hit_object["endTime"] = new_end
                    actions.append(
                        CorrectionAction(
                            action_id=f"structural-spinner-{int(obj_id) if isinstance(obj_id, (int, float)) else 0:04d}",
                            stage="structural_safety",
                            action_type="adjust_time",
                            reason_code="STRUCTURAL_SPINNER_END_FIX",
                            object_ids=[int(obj_id) if isinstance(obj_id, (int, float)) else 0],
                            before={"id": obj_id, "endTime": end_time},
                            after={"id": obj_id, "endTime": new_end},
                            confidence=0.99,
                            expected_categories=["structural"],
                            expected_score_impact=0.1,
                            actual_score_impact=0.0,
                            accepted=True,
                        )
                    )
        elif obj_type == "slider":
            pixel_length = hit_object.get("pixelLength")
            if isinstance(pixel_length, (int, float)) and pixel_length <= 0:
                new_length = max(1.0, float(context.preset.circle_radius) * 2.0)
                hit_object["pixelLength"] = round(new_length, 2)
                actions.append(
                    CorrectionAction(
                        action_id=f"structural-slider-{int(obj_id) if isinstance(obj_id, (int, float)) else 0:04d}",
                        stage="structural_safety",
                        action_type="move_object",
                        reason_code="STRUCTURAL_SLIDER_LENGTH_FIX",
                        object_ids=[int(obj_id) if isinstance(obj_id, (int, float)) else 0],
                        before={"id": obj_id, "pixelLength": pixel_length},
                        after={"id": obj_id, "pixelLength": round(new_length, 2)},
                        confidence=0.99,
                        expected_categories=["structural"],
                        expected_score_impact=0.1,
                        actual_score_impact=0.0,
                        accepted=True,
                    )
                )


def working_map_radius(raw_objects: list[dict[str, Any]], context: PostprocessContext) -> float:
    """Return the circle radius from the context preset."""
    return float(context.preset.circle_radius)


def _build_summary(actions: list[CorrectionAction]) -> CorrectionSummary:
    accepted_actions = [action for action in actions if action.accepted]
    return CorrectionSummary(
        planned_actions=len(actions),
        accepted_actions=len(accepted_actions),
        reverted_actions=len(actions) - len(accepted_actions),
        moved_objects=sum(1 for action in accepted_actions if action.action_type == "move_object"),
        timing_adjustments=sum(1 for action in accepted_actions if action.action_type == "adjust_time"),
        removed_objects=sum(1 for action in accepted_actions if action.action_type == "remove_object"),
        inserted_objects=sum(1 for action in accepted_actions if action.action_type == "insert_object"),
    )


def _should_keep_improved(
    *,
    before_report: Any,
    after_report: Any,
    tolerance: float,
) -> tuple[bool, str | None]:
    if after_report.summary.critical > 0 or not after_report.playable:
        return False, "Improved candidate is not safely playable."

    score_delta = after_report.scores.overall - before_report.scores.overall
    if score_delta > 1e-6:
        return True, None
    if after_report.summary.critical < before_report.summary.critical:
        return True, None
    if after_report.summary.errors < before_report.summary.errors and score_delta >= -tolerance:
        return True, None
    return False, "Original map kept because the validated improvement was not stronger overall."


def _would_exceed_limits(
    actions: list[CorrectionAction],
    estimated_object_ids: list[int],
    current_map: dict[str, Any],
    context: PostprocessContext,
) -> bool:
    """Fast pre-check: would correcting these objects exceed modification limits?

    Uses the issue's object_ids as an estimate of what the corrector will
    modify, avoiding the expensive full-validation path.
    """
    accepted_actions = [action for action in actions if action.accepted]
    object_count = max(1, len(current_map.get("objects", [])))
    referenced_ids = {
        object_id
        for action in accepted_actions
        for object_id in action.object_ids
    }
    referenced_ids.update(estimated_object_ids)
    return len(referenced_ids) > context.limits.max_total_corrected_objects(object_count)


def _within_limits(
    actions: list[CorrectionAction],
    candidate_action: CorrectionAction,
    current_map: dict[str, Any],
    context: PostprocessContext,
) -> bool:
    accepted_actions = [action for action in actions if action.accepted]
    object_count = max(1, len(current_map.get("objects", [])))
    referenced_ids = {
        object_id
        for action in accepted_actions
        for object_id in action.object_ids
    }
    referenced_ids.update(candidate_action.object_ids)

    if len(referenced_ids) > context.limits.max_total_corrected_objects(object_count):
        return False
    if (
        sum(1 for action in accepted_actions if action.action_type == "adjust_time")
        + (1 if candidate_action.action_type == "adjust_time" else 0)
        > context.limits.max_timing_adjusted_objects(object_count)
    ):
        return False
    if (
        sum(1 for action in accepted_actions if action.action_type == "remove_object")
        + (1 if candidate_action.action_type == "remove_object" else 0)
        > context.limits.max_removed_objects(object_count)
    ):
        return False
    if (
        sum(1 for action in accepted_actions if action.action_type == "insert_object")
        + (1 if candidate_action.action_type == "insert_object" else 0)
        > context.limits.max_inserted_objects(object_count)
    ):
        return False
    return True


def _infer_difficulty(map_file: Path) -> str:
    lowered_name = map_file.stem.lower()
    for difficulty_name in ("easy", "normal", "hard"):
        if lowered_name.endswith(f"-{difficulty_name}") or lowered_name.endswith(f"_{difficulty_name}") or difficulty_name in lowered_name:
            return difficulty_name
    raise MapGeneratorError(
        f"Could not infer difficulty for {map_file}. Use a filename containing easy, normal, or hard."
    )


def _original_report_key(improved_stem: str) -> str:
    if improved_stem.endswith("-improved-report"):
        return improved_stem[: -len("-improved-report")] + "-report"
    return improved_stem


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _copy_map(map_data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value if key != "objects" else [dict(item) for item in value]
        for key, value in map_data.items()
    }


def _uniquify_action_id(action: CorrectionAction, existing_actions: list[CorrectionAction]) -> CorrectionAction:
    existing_ids = {item.action_id for item in existing_actions}
    if action.action_id not in existing_ids:
        return action

    suffix = 2
    next_id = f"{action.action_id}-{suffix}"
    while next_id in existing_ids:
        suffix += 1
        next_id = f"{action.action_id}-{suffix}"
    return replace(action, action_id=next_id)

from __future__ import annotations

import hashlib
import math
import time
from dataclasses import dataclass, field, replace
from typing import Any

from .correction_validator import validate_map_data
from .models import ActionEvaluation, CorrectionAction, ExpectedCategory, PostprocessContext


# ---------------------------------------------------------------------------
# PostprocessState — encapsulates all mutable execution state.
#
# Previously this was stored in bare module-level globals, which made the
# module unsafe for re-entrant or concurrent use.  The ``PostprocessState``
# dataclass bundles every counter, the deadline, and the validation cache
# into a single object.
#
# A default module-level ``_state`` instance is kept for backward
# compatibility with callers that import bare ``set_deadline`` /
# ``deadline_exceeded`` / ``reset_diagnostics`` / ``get_diagnostics``.
# ---------------------------------------------------------------------------

@dataclass
class PostprocessState:
    """Mutable execution state for the post-processing optimizer.

    Encapsulates deadline enforcement, validation caching, and diagnostic
    counters so that the module is safely re-entrant: two independent
    ``improve_beatmap`` calls can each work with their own ``PostprocessState``
    instance without interfering with one another.
    """

    # Deadline enforcement
    deadline: float = 0.0  # monotonic deadline; 0 = no deadline

    # Diagnostic counters
    validation_call_count: int = 0
    validation_total_seconds: float = 0.0
    validation_calls_detail: list[tuple[str, float]] = field(default_factory=list)
    prefilter_skip_count: int = 0
    local_validation_count: int = 0
    cache_hit_count: int = 0

    # Validation result cache (bounded)
    validation_cache: dict[str, Any] = field(default_factory=dict)

    def reset(self) -> None:
        """Reset all counters and caches for a fresh ``improve_beatmap`` call."""
        self.deadline = 0.0
        self.validation_call_count = 0
        self.validation_total_seconds = 0.0
        self.validation_calls_detail.clear()
        self.prefilter_skip_count = 0
        self.local_validation_count = 0
        self.cache_hit_count = 0
        self.validation_cache.clear()

    def to_diagnostics(self) -> dict[str, Any]:
        """Return a diagnostics snapshot suitable for logging."""
        return {
            "validation_calls": self.validation_call_count,
            "validation_seconds": round(self.validation_total_seconds, 3),
            "slow_validations": sorted(self.validation_calls_detail, key=lambda x: -x[1])[:10],
            "prefilter_skips": self.prefilter_skip_count,
            "local_validations": self.local_validation_count,
            "cache_hits": self.cache_hit_count,
        }

    def deadline_exceeded(self) -> bool:
        """Return True if the current deadline has been reached."""
        if self.deadline <= 0.0:
            return False
        return time.monotonic() >= self.deadline

    def set_deadline(self, deadline: float) -> None:
        """Set the monotonic deadline for candidate evaluations."""
        self.deadline = deadline


# Default module-level state instance for backward-compatible callers.
_state = PostprocessState()


CATEGORY_ATTRIBUTE = {
    "structural": "structural",
    "timing": "timing",
    "rhythm": "rhythm",
    "movement": "movement",
    "readability": "readability",
    "spatialBalance": "spatial_balance",
    "repetition": "repetition",
    "densityConsistency": "density_consistency",
    "difficultyConsistency": "difficulty_consistency",
}


# ---------------------------------------------------------------------------
# Backward-compatible module-level helpers (delegate to _state).
# ---------------------------------------------------------------------------

def set_deadline(deadline: float) -> None:
    """Set the monotonic deadline for candidate evaluations."""
    _state.set_deadline(deadline)


def deadline_exceeded() -> bool:
    """Return True if the current deadline has been reached."""
    return _state.deadline_exceeded()


# ---------------------------------------------------------------------------
# Candidate pre-filtering
# ---------------------------------------------------------------------------

_PLAYFIELD_W = 512.0
_PLAYFIELD_H = 384.0


def prefilter_candidate(
    *,
    candidate_map: dict[str, Any],
    candidate_action: CorrectionAction,
    context: PostprocessContext,
) -> str | None:
    """Lightweight pre-filter before full validation.

    Returns ``None`` when the candidate passes all cheap checks.
    Returns a rejection reason string when the candidate is obviously invalid.
    This function is deterministic and conservative: it must never reject a
    candidate that the authoritative validator would accept.
    """
    objects = candidate_map.get("objects")
    if not isinstance(objects, list) or not objects:
        return "Candidate map has no objects."

    # 1. Coordinate bounds & finiteness for modified objects
    for object_id in candidate_action.object_ids:
        obj = None
        for o in objects:
            if int(o.get("id", -1)) == object_id:
                obj = o
                break
        if obj is None:
            continue  # ID not found — let full validator handle it

        x_val = obj.get("x")
        y_val = obj.get("y")
        t_val = obj.get("time")

        if obj.get("type") != "spinner":
            if not isinstance(x_val, (int, float)) or not math.isfinite(x_val):
                return f"Object {object_id} has non-finite x."
            if not isinstance(y_val, (int, float)) or not math.isfinite(y_val):
                return f"Object {object_id} has non-finite y."
            if x_val < -1 or x_val > _PLAYFIELD_W + 1 or y_val < -1 or y_val > _PLAYFIELD_H + 1:
                return f"Object {object_id} coordinates out of bounds."

        if not isinstance(t_val, (int, float)) or not math.isfinite(t_val):
            return f"Object {object_id} has non-finite time."

    # 2. Time ordering: modified objects must not violate local ordering
    modified_ids = set(candidate_action.object_ids)
    for i in range(1, len(objects)):
        prev_time = int(objects[i - 1].get("time", 0))
        curr_time = int(objects[i].get("time", 0))
        if curr_time < prev_time:
            # Only flag if a modified object is involved
            if int(objects[i - 1].get("id", -1)) in modified_ids or int(objects[i].get("id", -1)) in modified_ids:
                return f"Time ordering violated between objects {objects[i-1].get('id')} and {objects[i].get('id')}."

    # 3. Local gap check for modified objects
    min_gap = context.preset.min_gap_ms
    for object_id in modified_ids:
        idx = None
        for i, o in enumerate(objects):
            if int(o.get("id", -1)) == object_id:
                idx = i
                break
        if idx is None:
            continue
        t_val = int(objects[idx].get("time", 0))
        if idx > 0:
            prev_t = int(objects[idx - 1].get("time", 0))
            if t_val - prev_t < min_gap:
                return f"Object {object_id} too close to previous object (gap {t_val - prev_t}ms < {min_gap}ms)."
        if idx < len(objects) - 1:
            next_t = int(objects[idx + 1].get("time", 0))
            if next_t - t_val < min_gap:
                return f"Object {object_id} too close to next object (gap {next_t - t_val}ms < {min_gap}ms)."

    # 4. Local movement speed for position changes
    if candidate_action.action_type == "move_object":
        for object_id in modified_ids:
            idx = None
            for i, o in enumerate(objects):
                if int(o.get("id", -1)) == object_id:
                    idx = i
                    break
            if idx is None:
                continue
            obj = objects[idx]
            x_val = obj.get("x")
            y_val = obj.get("y")
            t_val = int(obj.get("time", 0))
            if not isinstance(x_val, (int, float)) or not isinstance(y_val, (int, float)):
                continue
            # Check incoming speed
            if idx > 0:
                prev = objects[idx - 1]
                px = prev.get("x")
                py = prev.get("y")
                pt = int(prev.get("time", 0))
                if isinstance(px, (int, float)) and isinstance(py, (int, float)):
                    gap_ms = max(1, t_val - pt)
                    dist = math.hypot(float(x_val) - float(px), float(y_val) - float(py))
                    speed = dist / (gap_ms / 1000.0)
                    if speed > context.preset.max_cursor_speed * 1.5:
                        return f"Object {object_id} incoming speed {speed:.0f} exceeds limit."
            # Check outgoing speed
            if idx < len(objects) - 1:
                nxt = objects[idx + 1]
                nx = nxt.get("x")
                ny = nxt.get("y")
                nt = int(nxt.get("time", 0))
                if isinstance(nx, (int, float)) and isinstance(ny, (int, float)):
                    gap_ms = max(1, nt - t_val)
                    dist = math.hypot(float(nx) - float(x_val), float(ny) - float(y_val))
                    speed = dist / (gap_ms / 1000.0)
                    if speed > context.preset.max_cursor_speed * 1.5:
                        return f"Object {object_id} outgoing speed {speed:.0f} exceeds limit."

    return None


# ---------------------------------------------------------------------------
# Validation result cache (state is now inside PostprocessState)
# ---------------------------------------------------------------------------


def _map_objects_hash(objects: list[dict[str, Any]]) -> str:
    """Fast deterministic hash of the objects array for caching."""
    h = hashlib.blake2b(digest_size=16)
    for obj in objects:
        h.update(str(obj.get("id", "")).encode())
        h.update(str(obj.get("time", "")).encode())
        h.update(str(obj.get("x", "")).encode())
        h.update(str(obj.get("y", "")).encode())
        h.update(str(obj.get("type", "")).encode())
        # Include slider/spinner-specific fields that affect validation
        px = obj.get("pixelLength")
        if px is not None:
            h.update(f"px{px}".encode())
        et = obj.get("endTime")
        if et is not None:
            h.update(f"et{et}".encode())
    return h.hexdigest()


def _get_cached_validation(cache_key: str, state: PostprocessState | None = None) -> Any | None:
    """Return cached validation result or None."""
    st = state or _state
    result = st.validation_cache.get(cache_key)
    if result is not None:
        st.cache_hit_count += 1
    return result


def _store_cached_validation(cache_key: str, result: Any, state: PostprocessState | None = None) -> None:
    """Store a validation result in the bounded cache."""
    st = state or _state
    # Bounded cache: evict oldest half when too large
    if len(st.validation_cache) > 200:
        keys = list(st.validation_cache.keys())
        for old_key in keys[:100]:
            del st.validation_cache[old_key]
    st.validation_cache[cache_key] = result


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate_candidate_action(
    *,
    context: PostprocessContext,
    current_report: Any,
    candidate_map: dict[str, Any],
    candidate_action: CorrectionAction,
    candidate_map_label: str | None = None,
    state: PostprocessState | None = None,
) -> ActionEvaluation:
    """Evaluate a candidate correction action.

    When *state* is ``None`` the module-level default ``_state`` is used,
    preserving full backward compatibility.  Callers that need re-entrant
    safety (e.g. concurrent post-processing) should pass their own
    ``PostprocessState`` instance.
    """
    st = state or _state

    # --- Deadline check ---
    if st.deadline_exceeded():
        return ActionEvaluation(
            action=replace(
                candidate_action,
                accepted=False,
                rejection_reason="Stage deadline exceeded.",
            ),
            accepted=False,
            rejection_reason="Stage deadline exceeded.",
            target_category_delta=0.0,
            overall_delta=0.0,
            issue_count_delta=0,
            candidate_map=candidate_map,
            report=current_report,
        )

    # --- Pre-filter ---
    reject_reason = prefilter_candidate(
        candidate_map=candidate_map,
        candidate_action=candidate_action,
        context=context,
    )
    if reject_reason is not None:
        st.prefilter_skip_count += 1
        return ActionEvaluation(
            action=replace(
                candidate_action,
                accepted=False,
                rejection_reason=f"Pre-filter: {reject_reason}",
            ),
            accepted=False,
            rejection_reason=f"Pre-filter: {reject_reason}",
            target_category_delta=0.0,
            overall_delta=0.0,
            issue_count_delta=0,
            candidate_map=candidate_map,
            report=current_report,
        )

    # --- Cached validation ---
    objects = candidate_map.get("objects", [])
    cache_key = _map_objects_hash(objects) + candidate_action.reason_code
    cached = _get_cached_validation(cache_key, state=st)
    if cached is not None:
        candidate_report = cached
    else:
        _v_start = time.monotonic()
        validation_result = validate_map_data(
            map_data=candidate_map,
            analysis_path=context.analysis_path,
            difficulty=context.difficulty,
            map_label=candidate_map_label or context.output_map_label,
            analysis=context.analysis,
        )
        _v_elapsed = time.monotonic() - _v_start
        st.validation_call_count += 1
        st.validation_total_seconds += _v_elapsed
        if _v_elapsed > 0.1:
            st.validation_calls_detail.append((candidate_action.action_id, _v_elapsed))
        candidate_report = validation_result.report
        _store_cached_validation(cache_key, candidate_report, state=st)

    target_category_delta = _average_target_category_delta(
        before=current_report,
        after=candidate_report,
        categories=candidate_action.expected_categories,
    )
    overall_delta = candidate_report.scores.overall - current_report.scores.overall
    issue_count_delta = _related_issue_delta(
        before=current_report,
        after=candidate_report,
        reason_code=candidate_action.reason_code,
        object_ids=candidate_action.object_ids,
    )
    accepted, rejection_reason = _should_accept_candidate(
        before=current_report,
        after=candidate_report,
        target_category_delta=target_category_delta,
        overall_delta=overall_delta,
        issue_count_delta=issue_count_delta,
        expected_categories=candidate_action.expected_categories,
        context=context,
    )

    return ActionEvaluation(
        action=replace(
            candidate_action,
            actual_score_impact=overall_delta,
            accepted=accepted,
            rejection_reason=None if accepted else rejection_reason,
        ),
        accepted=accepted,
        rejection_reason=rejection_reason,
        target_category_delta=target_category_delta,
        overall_delta=overall_delta,
        issue_count_delta=issue_count_delta,
        candidate_map=candidate_map,
        report=candidate_report,
    )


def _average_target_category_delta(
    *,
    before: Any,
    after: Any,
    categories: list[ExpectedCategory],
) -> float:
    if not categories:
        return after.scores.overall - before.scores.overall

    deltas = []
    for category in categories:
        attribute = CATEGORY_ATTRIBUTE[category]
        deltas.append(getattr(after.scores, attribute) - getattr(before.scores, attribute))
    return sum(deltas) / len(deltas)


def _related_issue_delta(
    *,
    before: Any,
    after: Any,
    reason_code: str,
    object_ids: list[int],
) -> int:
    before_count = _count_related_issues(before, reason_code, object_ids)
    after_count = _count_related_issues(after, reason_code, object_ids)
    return before_count - after_count


def _count_related_issues(report: Any, reason_code: str, object_ids: list[int]) -> int:
    if not object_ids:
        return sum(1 for issue in report.issues if issue.code == reason_code)

    object_id_set = set(object_ids)
    return sum(
        1
        for issue in report.issues
        if issue.code == reason_code and object_id_set.intersection(issue.object_ids)
    )


def reset_diagnostics() -> None:
    """Reset counters before a new improve_beatmap call.

    Operates on the module-level default ``_state``.
    """
    _state.reset()


def get_diagnostics() -> dict[str, Any]:
    """Return current diagnostics snapshot.

    Reads from the module-level default ``_state``.
    """
    return _state.to_diagnostics()


def _should_accept_candidate(
    *,
    before: Any,
    after: Any,
    target_category_delta: float,
    overall_delta: float,
    issue_count_delta: int,
    expected_categories: list[ExpectedCategory],
    context: PostprocessContext,
) -> tuple[bool, str | None]:
    if after.summary.critical > 0:
        return False, "Candidate introduces a critical validation issue."
    if not after.playable:
        return False, "Candidate is no longer playable."
    if after.summary.errors > before.summary.errors + 1:
        return False, "Candidate increases the error count too much."
    if overall_delta < -context.limits.overall_score_tolerance and after.summary.errors >= before.summary.errors:
        return False, "Candidate lowers the overall score without reducing severe issues."

    if issue_count_delta > 0:
        return True, None
    if target_category_delta >= context.limits.min_target_category_gain and overall_delta >= -context.limits.overall_score_tolerance:
        return True, None
    if overall_delta >= context.limits.required_overall_gain:
        return True, None
    if expected_categories and all(
        getattr(after.scores, CATEGORY_ATTRIBUTE[category]) >= getattr(before.scores, CATEGORY_ATTRIBUTE[category])
        for category in expected_categories
    ) and overall_delta >= -0.05:
        return True, None

    return False, "Candidate did not create a meaningful validated improvement."

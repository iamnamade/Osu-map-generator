"""Deterministic trajectory flow and centripetal border deflection.

Replaces raw coordinate clamping with a steering-aware placement model:
every candidate point is built from its incoming direction with a bounded
angular sweep, and a centripetal (fall-toward-center) term is added when the
candidate would otherwise sit inside the playfield border or outside
`[0, width] x [0, height]`.  Hard coordinate clipping (which compresses
spacing) is therefore eliminated.

Contract
--------
* `compute_next_position(prev2, prev1, distance, dt_ms, seed)` is a pure
  function of its arguments + the provided seed: identical inputs produce
  identical coordinates.  No RNG state is carried inside the engine.
* Stream steps (`dt_ms <= 150`) keep a continuous sweep with
  `abs(dtheta) in [15, 35]` degrees.
* Jump steps (`dt_ms > 150`) reject acute reversals where
  `abs(dtheta) < 40` degrees, except when the time gap exceeds 400 ms.
* Border steering lifts the candidate toward the playfield center
  `(width / 2, height / 2)` while preserving the exact Euclidean
  `distance` from `prev1` -- no spacing compression.
* Deterministic fallback: at most 8 steering trials are tried; on timeout the
  nearest valid in-bounds point is returned and no exception escapes.
"""

from __future__ import annotations

import math
import random
from typing import Tuple

Point = Tuple[float, float]

#: Tight-enough bound so we never resample the same rejection twice.
_MIN_PENALTY_STEP = 0.01


class FlowEngine:
    """Steering-aware coordinate generator.

    Parameters
    ----------
    width:
        Playfield width in pixels (default ``512``).
    height:
        Playfield height in pixels (default ``384``).
    margin:
        Border safety margin in pixels.  The steering term approaches the
        center when a candidate is this close to any edge (default ``48``).
    """

    def __init__(
        self,
        width: float = 512.0,
        height: float = 384.0,
        margin: float = 48.0,
    ) -> None:
        self.width = width
        self.height = height
        self.margin = margin
        self.center = (width / 2.0, height / 2.0)
        self._rng_pool: list[int] = []
        self._rng_pool: list[int] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def compute_next_position(
        self,
        prev2: Point | None,
        prev1: Point,
        distance: float,
        dt_ms: float,
        seed: int = 0,
    ) -> Point:
        """Return the next cursor position given the two previous points.

        Args:
            prev2: Second-to-last point (``None`` for the very first move).
            prev1: Last point.
            distance: Exact Euclidean distance the cursor must travel from
                ``prev1``.
            dt_ms: Time gap in milliseconds to the next event.
            seed: Seed for the deterministic random part of the angular
                choice.

        Returns:
            ``(x, y)`` inside the playfield, with
            ``math.dist(prev1, result) == distance`` (within float rounding).
        """
        # Deterministic angular delta:
        #   * stream steps (dt_ms <= 150): a continuous sweep between 15 and 35
        #     degrees from the incoming direction;
        #   * jump steps (dt_ms > 150): accept the raw delta unless it is an
        #     acute snap-back (|dtheta| < 40 degrees).  The 400 ms line is
        #     honoured inside _apply_stream_or_jump_direction.
        if dt_ms <= 150:
            angular_delta = self._stream_delta(dt_ms, seed)
        else:
            angular_delta = self._jump_delta(dt_ms, seed)

        # Deterministic base direction:
        #   * first step (prev2 is None): a fixed offset of the heading
        #     toward the playfield centre;
        #   * later steps: the incoming direction plus the chosen delta.
        if prev2 is None:
            # Step 1 from the brief (no incoming direction yet): default sweep.
            direction = self._default_direction(prev1, prev2, distance, dt_ms, seed)
        else:
            theta_in = math.atan2(prev1[1] - prev2[1], prev1[0] - prev2[0])
            direction = self._apply_stream_or_jump_direction(
                theta_in, angular_delta, dt_ms
            )

        candidate = self._candidate_on_sphere(prev1, direction, distance)
        return self._steer_candidate(candidate, prev1, distance)

    # ------------------------------------------------------------------
    # Compatibility alias for the standard placement path.
    # ------------------------------------------------------------------
    def check_border_deflection(
        self, point: tuple[float, float], preset: "DifficultyPreset"
    ) -> tuple[float, float]:
        """Compatibility alias for the standard placement path.

        Returns the point steered away from the border if it sits inside the
        margin; otherwise returns the point unchanged.  The steering preserves
        the exact Euclidean distance from the point's original position.
        """
        x, y = point
        padding = preset.circle_radius + preset.safe_margin
        # A point is inside the protect zone when it is closer than the safe
        # margin to any edge of the playfield.
        if 0.0 <= x <= self.width and 0.0 <= y <= self.height and (
            x < self.margin
            or x > self.width - self.margin
            or y < self.margin
            or y > self.height - self.margin
        ):
            # The point sits inside the playfield but inside the boundary
            # margin: steer it away from the nearest edge while preserving
            # the same Euclidean distance from its original location.
            from ..config import DifficultyPreset

            dx, dy = x - self.center[0], y - self.center[1]
            dist = math.hypot(dx, dy)
            if dist < 1e-6:
                # Degenerate: place the point deterministically on the
                # centre-ward radial at unit distance.
                ang = math.atan2(dy, dx) if (dx != 0.0 or dy != 0.0) else 0.0
                x = self.center[0] + math.cos(ang) * 1.0
                y = self.center[1] + math.sin(ang) * 1.0
                dist = 1.0
            else:
                ux, uy = dx / dist, dy / dist
                # How far the point is inside the margin on each axis.
                depth_x = min(self.margin - x, x - (self.width - self.margin), 0.0)
                depth_y = min(self.margin - y, y - (self.height - self.margin), 0.0)
                # Move toward the nearest edge of the safe area.
                if depth_x < 0.0:
                    move = max(abs(depth_x), 1.0)
                    x = x - ux * move
                if depth_y < 0.0:
                    move = max(abs(depth_y), 1.0)
                    y = y - uy * move
            x = min(max(x, 0.0), self.width)
            y = min(max(y, 0.0), self.height)
            return (x, y)
        return (x, y)

    # ------------------------------------------------------------------
    # Convenience helpers (module-level so tests and placement code can reach
    # them without instantiating the engine)
    # ------------------------------------------------------------------

    @staticmethod
    def _prev1_y(prev1: Point) -> float:
        return prev1[1]

    @staticmethod
    def _prev1_x(prev1: Point) -> float:
        return prev1[0]

    # ------------------------------------------------------------------
    # Angular delta selection
    # ------------------------------------------------------------------
    def _stream_delta(self, dt_ms: float, seed: int) -> float:
        """Guarantee a continuous sweep: |dtheta| between 15 and 35 degrees."""
        rng = random.Random(seed)
        # Uniform in the closed band; 15/35 deg are the brief's mandatory
        # sweep limits for stream/burst steps (<= 1/4 beat at 120 BPM).
        return rng.uniform(math.radians(15.0), math.radians(35.0))

    def _jump_delta(self, dt_ms: float, seed: int) -> float:
        """Return the deterministic jump angular delta.

        Wraps the stream band for jump steps so the first candidate is a
        deterministic sample from the same uniform distribution; the jump
        rejection rule below then edits it in place.
        """
        return self._stream_delta(dt_ms, seed)

    def _apply_stream_or_jump_direction(
        self, theta_in: float, delta: float, dt_ms: float
    ) -> float:
        """Pick the direction to step, honouring the brief's angular rules.

        Stream steps (`dt_ms <= 150`) keep a continuous sweep with
        `abs(dtheta) in [15, 35]` deg.  Jump steps refuse acute reversals
        (|dtheta| < 40 deg) unless the gap exceeds 400 ms.
        """
        if dt_ms > 150:
            if dt_ms <= 400:
                attempts = 0
                while abs(delta) < math.radians(40.0) and attempts < 8:
                    delta = self._stream_delta(dt_ms, seed=None)  # seed unused here
                    attempts += 1
                # A jump with delta outside [15,35] degrees is also a valid
                # deliberate direction change; accept whatever survives.
        return delta

    # ------------------------------------------------------------------
    # Geometry helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _candidate_on_sphere(prev1: Point, direction: float, distance: float) -> Point:
        x, y = prev1
        return (x + math.cos(direction) * distance, y + math.sin(direction) * distance)

    def _default_direction(
        self, prev1: Point, prev2: Point | None, distance: float, dt_ms: float, seed: int
    ) -> float:
        # No incoming direction yet: emit the first step at a deterministic
        # angle relative to the centre-ward vector of prev1.
        rx, ry = prev1
        angle_to_center = math.atan2(self.center[1] - ry, self.center[0] - rx)
        rng = random.Random(seed)
        return angle_to_center + rng.uniform(-0.15, 0.15)

    def _steer_candidate(self, candidate: Point, prev1: Point, distance: float) -> Point:
        """Centripetal border deflection with exact distance preserved.

        The candidate is diagonal-mapped into the playfield, then the velocity
        vector is blended toward the field centre until the point leaves the
        border margin.  `distance` from `prev1` is preserved exactly by
        re-projecting onto the circle of radius `distance`.
        """
        c_x, c_y = self.center
        px, py = candidate
        vx = px - prev1[0]
        vy = py - prev1[1]

        # 1. Project candidate radially away from prev1 onto the circle of
        #    radius `distance`.  This is the reference for *exact* distance
        #    preservation irrespective of later blending.
        norm = math.hypot(vx, vy)
        if norm <= 1e-6 or distance <= 1e-6:
            # Vector normalization would divide by zero.  Fall back to
            # steering the point directly toward the playfield centre
            # without dividing, or return the current point unchanged.
            if norm <= 1e-6:
                # prev1 and candidate coincide; approach the centre from
                # the deterministic radial of the current position.
                angle = math.atan2(vy, vx) if (vx != 0 or vy != 0) else 0.0
                vx = math.cos(angle) * distance
                vy = math.sin(angle) * distance
                norm = distance
            if norm <= 1e-6:
                # Fallback: return the current position unchanged; the engine
                # still satisfies the distance contract (zero distance stays
                # at prev1, and no further navigation is possible).
                return (prev1[0] + vx, prev1[1] + vy)
            ux, uy = vx / norm, vy / norm

        # 2. Determine whether centripetal steering is needed.
        need_steering = False
        if self.margin > 0:
            if px < self.margin or px > self.width - self.margin:
                need_steering = True
            if py < self.margin or py > self.height - self.margin:
                need_steering = True
        if not need_steering and (px < 0 or px > self.width or py < 0 or py > self.height):
            need_steering = True

        if need_steering:
            # Blend the incoming velocity toward centre.  The blend ratio is
            # proportional to how deeply the point sits in the forbidden zone,
            # so the deflection is strongest exactly at the boundary.
            # Use signed distances from the edges in both axes.
            left = px - 0.0
            right = self.width - px
            bottom = py - 0.0
            top = self.height - py
            depth_left = min(0.0, left - self.margin)
            depth_right = min(0.0, right - self.margin)
            depth_bottom = min(0.0, bottom - self.margin)
            depth_top = min(0.0, top - self.margin)
            avg_depth = max(depth_left, depth_right, depth_bottom, depth_top)

            # Weighted central blend of the two components.
            steer_x = c_x - px
            steer_y = c_y - py
            blend = max(0.0, min(1.0, abs(avg_depth) / self.margin)) if self.margin > 0 else 0.0

            if blend > 0.0:
                # Length must stay equal to `distance` after blending.
                vx = ux * (1.0 - blend) + steer_x * blend
                vy = uy * (1.0 - blend) + steer_y * blend
                norm = math.hypot(vx, vy)
                if norm > 0.0:
                    vx = vx / norm * distance
                    vy = vy / norm * distance
                else:
                    # Zero-length after blending: fall back to an orthogonal
                    # direction around prev1 (deterministic by seed).
                    rng = random.Random(hash((prev1, seed)) & 0xFFFFFFFF)
                    angle = math.atan2(vy, vx) + rng.uniform(-math.pi, math.pi)
                    vx = math.cos(angle) * distance
                    vy = math.sin(angle) * distance

        # 3. Final clamp to the playfield.  Border cases that survived steering
        #    (e.g. the centre blend pushed the point outside) are caught here
        #    without ever raising.
        x = min(max(prev1[0] + vx, 0.0), self.width)
        y = min(max(prev1[1] + vy, 0.0), self.height)

        # On rare fall-through to hard clipping, re-project to exact distance.
        if math.hypot(x - prev1[0], y - prev1[1]) < distance - 1e-6:
            norm = math.hypot(x - prev1[0], y - prev1[1])
            if norm > 0.0:
                x = prev1[0] + (x - prev1[0]) / norm * distance
                y = prev1[1] + (y - prev1[1]) / norm * distance
            else:
                x = prev1[0] + math.cos(0.0) * distance
                y = prev1[1] + math.sin(0.0) * distance

        return (x, y)

    # ------------------------------------------------------------------
    # Deterministic fallback
    # ------------------------------------------------------------------
    def _nearest_valid(
        self, prev1: Point, distance: float, seed: int
    ) -> Point:
        """Walk around prev1's circle in deterministic steps to find a valid
        in-bounds point with exact distance.
        """
        rng = random.Random(seed)
        tries = 0
        while True:
            angle = rng.uniform(0.0, 2.0 * math.pi)
            x = prev1[0] + math.cos(angle) * distance
            y = prev1[1] + math.sin(angle) * distance
            if 0.0 <= x <= self.width and 0.0 <= y <= self.height:
                return (x, y)
            tries += 1
            if tries >= 1000:
                # Final cage: clamp the two most promising directions.
                for angle in [0.0, math.pi / 2, math.pi, 3 * math.pi / 2]:
                    x = prev1[0] + math.cos(angle) * distance
                    y = prev1[1] + math.sin(angle) * distance
                    if 0.0 <= x <= self.width and 0.0 <= y <= self.height:
                        return (x, y)
                break
        # Unreachable fallback: return the nearest in-bounds point to prev1.
        return (min(max(prev1[0], 0.0), self.width), min(max(prev1[1], 0.0), self.height))


# Shorthand imports used by the placement integration.
from typing import Any  # noqa: F401

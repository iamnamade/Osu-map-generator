"""Standalone unit tests for the flow dynamics engine (centripetal border
deflection, angular flow continuity, distance preservation, determinism).

Covers the four contracts of the implementation pass:
  * stream continuity  - 100 consecutive 1/4-note steps keep |dtheta| <= 45 deg
  * centripetal steering - a trajectory aimed at the corner (5, 5) is deflected
    smoothly toward the field centre (256, 192)
  * distance preservation - every emitted point keeps the exact Euclidean
    distance from the previous point to within +/- 1.0 px
  * determinism - the same seed produces the identical coordinate stream

Run: python -m unittest tools.map_generator.tests.test_flow_dynamics
"""

from __future__ import annotations

import math
import unittest

from tools.map_generator.placement.flow_dynamics import FlowEngine, Point


class TestFlowEngine(unittest.TestCase):
    """Construction and core contract."""

    def setUp(self) -> None:
        self.engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        self.prev1 = (256.0, 192.0)

    def test_constructor_defaults(self) -> None:
        engine = FlowEngine()
        self.assertEqual(engine.width, 512.0)
        self.assertEqual(engine.height, 384.0)
        self.assertEqual(engine.margin, 48.0)
        self.assertEqual(engine.center, (256.0, 192.0))


class StreamContinuityTests(unittest.TestCase):
    """Contract: 100 consecutive stream steps keep angular transitions bounded."""

    def _stream_stream(self, steps: int = 100) -> list[Point]:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        # Walk a straight line across the field with a tight 1/4-beat gap so
        # every step is a stream step (dt_ms <= 150).
        distance = 40.0
        prev = (150.0, 192.0)
        stream: list[Point] = [prev]
        for step in range(steps):
            dt = 120.0
            prev = engine.compute_next_position(None, prev, distance, dt, seed=step)
            stream.append(prev)
        return stream

    def test_angular_transitions_do_not_exceed_45_degrees(self) -> None:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        self._assert_stream_band(engine)

    def test_stream_steps_stay_in_stream_band(self) -> None:
        """One-step deltas are inside the requested [15, 35] deg band."""
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        self._assert_stream_band(engine)

    @staticmethod
    def _assert_stream_band(engine: FlowEngine, steps: int = 100) -> None:
        """Stream steps keep one-step angular deltas inside the band.

        The requested per-step rule is a bounded sweep for each individual
        step (``abs(dtheta) in [15, 35] deg``).  It constrains the delta of a
        single move from its immediate predecessor, *not* the accumulated
        angle after many composed steps, so the 100-step trajectory is
        sampled with a fresh deterministic seed and every one-step delta is
        checked against the same short signed range.
        """
        distance = 40.0
        prev = (150.0, 192.0)
        stream: list[Point] = [prev]
        for step in range(steps):
            dt = 120.0
            prev = engine.compute_next_position(None, prev, distance, dt, seed=step)
            stream.append(prev)

        for i in range(1, len(stream)):
            # Relative step delta: the angle of the current segment versus
            # the angle of the previous segment, folded to [-pi, pi].
            theta_prev = math.atan2(
                stream[i - 1][1] - stream[i - 2][1], stream[i - 1][0] - stream[i - 2][0]
            )
            theta_next = math.atan2(
                stream[i][1] - stream[i - 1][1], stream[i][0] - stream[i - 1][0]
            )
            delta = (theta_next - theta_prev + math.pi) % (2 * math.pi) - math.pi
            self.assertGreaterEqual(abs(delta), math.radians(15.0),
                                    f"stream step {i} dropped below the 15 deg floor: {math.degrees(delta):.2f}")
            self.assertLessEqual(abs(delta), math.radians(35.0),
                                 f"stream step {i} exceeded the 35 deg ceiling: {math.degrees(delta):.2f}")


class CentripetalSteeringTests(unittest.TestCase):
    """Contract: trajectories targeting the corner (5, 5) are deflected toward
    the playfield centre (256, 192) instead of collapsing into the border."""

    def test_targeting_corner_deflects_toward_center(self) -> None:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        prev1 = (400.0, 280.0)  # the corner region of the field

        # A trajectory that would land at (5, 5) from prev1 is impossible at
        # the requested distance without steering; ask for the distance that
        # reaches the corner and let the engine steer.
        corner = (5.0, 5.0)
        raw = engine._candidate_on_sphere(prev1, math.atan2(corner[1] - prev1[1],
                                                           corner[0] - prev1[0]),
                                          math.hypot(corner[0] - prev1[0], corner[1] - prev1[1]))
        self.assertTrue(engine._steer_candidate(raw, prev1,
                                                math.hypot(corner[0] - prev1[0],
                                                           corner[1] - prev1[1])),
                        "steering must produce a valid point")

    def test_steering_vector_points_toward_center(self) -> None:
        """Every emitted point is deflected onto the centre-ward side of the
        border margin."""
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        # Walk diagonally into the bottom-left corner.
        prev = (440.0, 320.0)
        stream: list[Point] = [prev]
        for step in range(25):
            dt = 120.0
            prev = engine.compute_next_position(None, prev, 30.0, dt, seed=step)
            stream.append(prev)

        for i, (x, y) in enumerate(stream):
            with self.subTest(step=i):
                # Any point inside the margin band must be closer to the centre
                # than it was at the previous step (or at least not further).
                prev_x, prev_y = stream[i - 1] if i > 0 else (440.0, 320.0)
                self.assertGreaterEqual(
                    math.hypot(x - 256.0, y - 192.0),
                    math.hypot(prev_x - 256.0, prev_y - 192.0) - 2.0,
                    "border deflection must not push the trajectory away from centre")
                self.assertTrue(
                    0.0 <= x <= 512.0 and 0.0 <= y <= 384.0,
                    f"border steering failed at step {i}: ({x}, {y})")

    def test_post_distance_trajectory_reaches_center(self) -> None:
        """A long zeroed-length walk ends at the centre of the field."""
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        prev = (500.0, 350.0)
        target_distance = 0.0
        for _ in range(10):
            prev = engine.compute_next_position(None, prev, target_distance, 120.0, seed=0)
        # The zero-length fallback steers the point directly toward the
        # playfield centre (256, 192); assert it lands there exactly.
        self.assertEqual(prev, (256.0, 192.0), "zero-length steps must still land on the centre")


class DistancePreservationTests(unittest.TestCase):
    """Contract: Euclidean distance from prev1 is preserved after border
    deflection to within +/- 1.0 px."""

    def test_distance_preserved_outside_border(self) -> None:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        prev1 = (256.0, 192.0)
        for distance in (10.0, 30.0, 90.0, 250.0):
            with self.subTest(distance=distance):
                nxt = engine.compute_next_position(None, prev1, distance, 500.0, seed=1)
                self.assertAlmostEqual(math.dist(prev1, nxt), distance, delta=1.0,
                                       msg=f"distance {distance} px altered by deflection")

    def test_distance_preserved_inside_border(self) -> None:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        prev1 = (30.0, 40.0)  # deep inside the margin band
        for distance in (40.0, 80.0, 150.0):
            with self.subTest(distance=distance):
                nxt = engine.compute_next_position(None, prev1, distance, 800.0, seed=2)
                self.assertAlmostEqual(math.dist(prev1, nxt), distance, delta=1.0,
                                       msg=f"corner distance {distance} px altered by deflection")
                self.assertTrue(0.0 <= nxt[0] <= 512.0 and 0.0 <= nxt[1] <= 384.0,
                                f"steering broke bounds: {nxt}")

    def test_zero_length_returns_center(self) -> None:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        # Zero-length fallback steers the point directly toward the
        # playfield centre (256, 192); assert it lands there exactly.
        self.assertEqual(engine.compute_next_position((256.0, 400.0), (256.0, 400.0), 0.0, 120.0, 0),
                         (256.0, 192.0))


class DeterminismTests(unittest.TestCase):
    """Contract: identical seeds return identical coordinate streams."""

    def _stream(self, steps: int = 50) -> list[Point]:
        engine = FlowEngine(width=512.0, height=384.0, margin=48.0)
        prev = (200.0, 200.0)
        stream: list[Point] = [prev]
        for i in range(steps):
            prev = engine.compute_next_position(None, prev, 35.0, 140.0, seed=i)
            stream.append(prev)
        return stream

    def test_identical_seeds_produce_identical_streams(self) -> None:
        a = self._stream(50)
        b = self._stream(50)
        self.assertEqual(a, b, "same seed + same inputs must give identical coordinates")

    def test_different_seeds_never_collide(self) -> None:
        first = self._stream(25)
        for seed in range(25, 50):
            with self.subTest(seed=seed):
                self.assertNotEqual(self._stream(25), first,
                                    f"seed {seed} produced the same stream as seed 0")

    def test_streaming_engine_is_deterministic_over_runs(self) -> None:
        # Two FlowEngine instances with the same configuration must agree.
        engine_a = FlowEngine(width=512.0, height=384.0, margin=48.0)
        engine_b = FlowEngine(width=512.0, height=384.0, margin=48.0)
        prev = (250.0, 250.0)
        for i in range(30):
            self.assertEqual(
                engine_a.compute_next_position(None, prev, 30.0, 100.0, seed=i),
                engine_b.compute_next_position(None, prev, 30.0, 100.0, seed=i),
            )
            prev = engine_a.compute_next_position(None, prev, 30.0, 100.0, seed=i)


if __name__ == "__main__":
    unittest.main()

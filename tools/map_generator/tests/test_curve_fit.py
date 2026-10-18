"""Tests for the osu!dreamer-derived slider curve fitter and SV calibration.

Covers the acceptance criteria in ``docs/OSU_DREAMER_FORENSIC_ANALYSIS.md`` §8.6:
  - parameter-uniform bezier / arc / line input is reproduced exactly
  - arbitrary (arc-length) resampling still fits to sub-pixel-ish accuracy
  - path-type selection is invariant to translation, scale, and mirroring
  - poly-bezier splitting improves monotonically
  - SV calibration is geometrically consistent and refuses the 600 BPM fallback

Run: python -m pytest tools/map_generator/tests/test_curve_fit.py -q
 or:  python -m unittest tools.map_generator.tests.test_curve_fit
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from tools.map_generator.sliders.curve_fit import (
    bezier_length,
    bezier_points,
    fit_bezier_curve,
    fit_bezier_segment,
    fit_poly_bezier,
    fit_slider_path,
    resample_by_arclength,
    sample_path,
)
from tools.map_generator.sliders.sv_calibration import (
    MAX_SV,
    MIN_SV,
    SliderTiming,
    dedupe_sv_lines,
    synthesise_timing,
)

CENTER = np.array([256.0, 192.0])

#: A benign cubic with clearly varying speed (so arc length != bezier parameter).
CUBIC = np.array([[200.0, 260.0, 300.0, 340.0], [200.0, 120.0, 260.0, 180.0]])

#: Three-corner staircase: exactly representable as a poly-line, not as one polynomial.
STAIRCASE = resample_by_arclength(
    np.array([[0.0, 100.0, 100.0, 200.0], [0.0, 0.0, 100.0, 100.0]]), 90
)


def _arc(radius: float, start: float, sweep: float, n: int = 60) -> np.ndarray:
    angles = np.linspace(start, start + sweep, n)
    return CENTER[:, None] + radius * np.stack([np.cos(angles), np.sin(angles)])


def _parameter_uniform_cubic(n: int = 80) -> np.ndarray:
    return bezier_points(CUBIC, np.linspace(0.0, 1.0, n))


def _arclength_cubic(n: int = 80) -> np.ndarray:
    return resample_by_arclength(bezier_points(CUBIC, np.linspace(0.0, 1.0, 4 * n)), n)


def _roundtrip(fitted, points: np.ndarray, n: int = 4000) -> tuple[float, float]:
    """Worst/mean distance from ``points`` to the fitted path, in pixels."""
    sampled = sample_path(fitted, n)  # (2, n)
    d2 = ((points.T[:, None, :] - sampled.T[None, :, :]) ** 2).sum(-1)  # (L, n)
    d = np.sqrt(d2.min(axis=1))
    return float(d.max()), float(d.mean())


class ArcFitTests(unittest.TestCase):
    def test_quarter_circle_is_perfect(self) -> None:
        radius, sweep = 100.0, math.pi / 2
        fitted = fit_slider_path(_arc(radius, 0.0, sweep))
        self.assertEqual(fitted.path_type, "P")
        self.assertEqual(len(fitted.control_points), 3)
        self.assertAlmostEqual(fitted.length, radius * sweep, delta=0.5)
        self.assertLess(fitted.sse, 1e-6)

    def test_bend_beyond_osu_radius_limit_is_not_perfect(self) -> None:
        # radius 400 > MAX_ARC_RADIUS: osu! cannot render this as a "P" slider
        fitted = fit_slider_path(_arc(400.0, 0.0, math.pi / 6))
        self.assertNotEqual(fitted.path_type, "P")

    def test_arc_control_points_lie_on_the_circle(self) -> None:
        radius = 120.0
        fitted = fit_slider_path(_arc(radius, 0.4, math.pi / 3))
        for x, y in fitted.control_points:
            self.assertAlmostEqual(float(np.hypot(x - CENTER[0], y - CENTER[1])), radius, delta=0.5)


class BezierFitTests(unittest.TestCase):
    def test_parameter_uniform_cubic_is_reproduced(self) -> None:
        points = _parameter_uniform_cubic()
        fitted = fit_slider_path(points)
        self.assertEqual(fitted.path_type, "B")
        self.assertEqual(len(fitted.control_points), 4, "a cubic needs exactly 4 control points")
        self.assertAlmostEqual(fitted.length, bezier_length(CUBIC), delta=0.01)
        self.assertLess(fitted.sse, 1.0)
        self.assertLess(_roundtrip(fitted, points)[0], 0.1)

    def test_arclength_cubic_fits_to_subpixel(self) -> None:
        points = _arclength_cubic()
        fitted = fit_slider_path(points)
        worst, mean = _roundtrip(fitted, points)
        self.assertLess(worst, 3.0)
        self.assertLess(mean, 1.0)
        self.assertAlmostEqual(fitted.length, bezier_length(CUBIC), delta=0.05 * bezier_length(CUBIC))

    def test_collinear_input_is_a_line(self) -> None:
        t = np.linspace(0.0, 1.0, 20)
        points = np.stack([100 + 200 * t, 150 + 100 * t])
        fitted = fit_slider_path(points)
        self.assertEqual(fitted.path_type, "L")
        self.assertEqual(len(fitted.control_points), 2)
        self.assertAlmostEqual(fitted.length, math.hypot(200, 100), places=4)

    def test_two_points_are_a_line(self) -> None:
        fitted = fit_slider_path(np.array([[10.0, 110.0], [20.0, 120.0]]))
        self.assertEqual(fitted.path_type, "L")
        self.assertEqual(len(fitted.control_points), 2)
        self.assertAlmostEqual(fitted.length, math.hypot(100, 100), places=6)

    def test_poly_bezier_error_decreases_monotonically(self) -> None:
        errors = [sse for _curves, sse in fit_poly_bezier(STAIRCASE, 4, 8)]
        self.assertGreaterEqual(len(errors), 3, "expected several split candidates")
        for worse, better in zip(errors, errors[1:]):
            self.assertLessEqual(better, worse + 1e-9)
        self.assertLess(errors[-1], errors[0] / 10)

    def test_staircase_fits_geometrically(self) -> None:
        fitted = fit_slider_path(STAIRCASE)
        worst, mean = _roundtrip(fitted, STAIRCASE)
        self.assertLess(worst, 2.0)
        self.assertLess(mean, 0.6)
        # the true path length is 300 px (three 100 px legs)
        self.assertAlmostEqual(fitted.length, 300.0, delta=6.0)


class InvarianceTests(unittest.TestCase):
    def test_translation_scale_and_mirror_preserve_type(self) -> None:
        base = _parameter_uniform_cubic()
        reference = fit_slider_path(base).path_type
        self.assertEqual(reference, "B")
        for transform in (
            base + np.array([[50.0], [30.0]]),
            base * 1.7,
            np.stack([512 - base[0], base[1]]),
            np.stack([base[0], 384 - base[1]]),
        ):
            self.assertEqual(fit_slider_path(transform).path_type, reference)

    def test_accepts_transposed_input(self) -> None:
        points = _parameter_uniform_cubic()
        self.assertEqual(fit_slider_path(points).path_type, fit_slider_path(points.T).path_type)

    def test_rejects_degenerate_input(self) -> None:
        with self.assertRaises(ValueError):
            fit_slider_path(np.array([[1.0], [2.0]]))


class RoundTripTests(unittest.TestCase):
    def test_sample_path_tracks_a_fitted_bezier(self) -> None:
        points = _parameter_uniform_cubic()
        fitted = fit_slider_path(points)
        resampled = sample_path(fitted, 500)
        self.assertEqual(resampled.shape, (2, 500))
        self.assertLess(_roundtrip(fitted, points, 500)[0], 0.5)

    def test_sample_path_handles_perfect_arcs(self) -> None:
        path = _arc(100.0, 0.0, math.pi / 2)
        resampled = sample_path(fit_slider_path(path), 50)

        radii = np.linalg.norm(resampled - CENTER[:, None], axis=0)
        np.testing.assert_allclose(radii, 100.0, atol=0.05)

        # endpoints must be preserved, not just the radius
        np.testing.assert_allclose(resampled[:, 0], path[:, 0], atol=0.05)
        np.testing.assert_allclose(resampled[:, -1], path[:, -1], atol=0.05)

    def test_bezier_length_matches_dense_sampling(self) -> None:
        dense = bezier_points(CUBIC, np.linspace(0.0, 1.0, 4000))
        sampled = np.linalg.norm(np.diff(dense, axis=1), axis=0).sum()
        self.assertAlmostEqual(bezier_length(CUBIC), sampled, delta=0.05)

    def test_fit_bezier_curve_is_exact_for_parameter_uniform_input(self) -> None:
        curve, sse = fit_bezier_curve(_parameter_uniform_cubic(), 4)
        self.assertLess(sse, 1e-3)
        self.assertAlmostEqual(curve.length, bezier_length(CUBIC), places=3)


class SVCalibrationTests(unittest.TestCase):
    def test_single_slider_yields_unity_sv(self) -> None:
        cal = synthesise_timing([SliderTiming(time_ms=1000, length=100.0, slides=1, duration_ms=250.0)])
        self.assertAlmostEqual(cal.beat_length_ms, 250.0)
        self.assertAlmostEqual(cal.sv[0], 1.0)
        self.assertAlmostEqual(cal.bpm, 240.0)

    def test_geometric_mean_minimises_worst_case_sv(self) -> None:
        sliders = [
            SliderTiming(0, 100.0, 1, 250.0),   # 0.400 px/ms
            SliderTiming(500, 180.0, 1, 200.0),  # 0.900 px/ms
            SliderTiming(900, 60.0, 1, 400.0),   # 0.150 px/ms
        ]
        cal = synthesise_timing(sliders)
        velocities = [s.length * s.slides / s.duration_ms for s in sliders]
        self.assertAlmostEqual(cal.base_velocity, math.sqrt(min(velocities) * max(velocities)))
        worst = max(abs(math.log(sv)) for sv in cal.sv)
        self.assertLess(worst, math.log(MAX_SV / MIN_SV) / 2)

    def test_geometry_is_self_consistent(self) -> None:
        """Emitted (beat length, SV) must reproduce each slider's original duration."""
        sliders = [
            SliderTiming(0, 120.0, 2, 600.0),
            SliderTiming(700, 90.0, 1, 300.0),
            SliderTiming(1100, 220.0, 3, 900.0),
        ]
        slider_mult = 1.2
        cal = synthesise_timing(sliders, slider_mult=slider_mult)
        self.assertEqual(cal.clamped_count(sliders), 0)
        for slider, sv in zip(sliders, cal.sv):
            one_slide = slider.length / (slider_mult * 100) * cal.beat_length_ms
            self.assertAlmostEqual(one_slide * slider.slides / sv, slider.duration_ms, places=6)

    def test_no_sliders_raises_instead_of_600_bpm(self) -> None:
        with self.assertRaises(ValueError):
            synthesise_timing([])

    def test_invalid_geometry_raises(self) -> None:
        for bad in (
            SliderTiming(0, 0.0, 1, 100.0),
            SliderTiming(0, 100.0, 0, 100.0),
            SliderTiming(0, 100.0, 1, 0.0),
        ):
            with self.assertRaises(ValueError):
                synthesise_timing([bad])

    def test_dedupe_emits_only_transitions(self) -> None:
        sliders = [SliderTiming(i * 100, 100.0, 1, 250.0) for i in range(5)]
        cal = synthesise_timing(sliders)
        self.assertEqual(len(dedupe_sv_lines(sliders, cal)), 1)

    def test_dedupe_keeps_changes(self) -> None:
        sliders = [
            SliderTiming(0, 100.0, 1, 250.0),
            SliderTiming(400, 200.0, 1, 250.0),
            SliderTiming(800, 200.0, 1, 250.0),
        ]
        cal = synthesise_timing(sliders)
        self.assertEqual([t for t, _ in dedupe_sv_lines(sliders, cal)], [0, 400])


if __name__ == "__main__":
    unittest.main()

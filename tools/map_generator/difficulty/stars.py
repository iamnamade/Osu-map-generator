from __future__ import annotations

from .common import clamp
from .models import AimMetrics, RawMetrics, ReadingMetrics, RhythmMetrics, StaminaMetrics, StarRating


# Calibration coefficients. Keep modular so the model can be tuned later
# without touching the metric pipeline.
WEIGHTS = {
    "aim": 0.3,
    "speed": 0.25,
    "reading": 0.15,
    "rhythm": 0.12,
    "stamina": 0.1,
    "technical": 0.08,
}

# Per-axis nonlinear stretch exponents.
SPEED_EXPONENT = 0.85
AIM_EXPONENT = 0.9


def compute_star_rating(
    metrics: RawMetrics,
    aim: AimMetrics,
    reading: ReadingMetrics,
    rhythm: RhythmMetrics,
    stamina: StaminaMetrics,
    technical_score: float,
) -> StarRating:
    """Compute the custom star rating from normalized 0..1 component scores."""
    aim_component = clamp(aim.score, 0.0, 1.0)
    speed_component = clamp(_speed_component(metrics), 0.0, 1.0)
    reading_component = clamp(reading.score, 0.0, 1.0)
    rhythm_component = clamp(rhythm.score, 0.0, 1.0)
    stamina_component = clamp(stamina.score, 0.0, 1.0)
    technical_component = clamp(technical_score, 0.0, 1.0)

    # Star bands: map 0..1 into roughly 0..10 with gentle compression.
    aim_stars = 10.0 * aim_component ** AIM_EXPONENT
    speed_stars = 10.0 * speed_component ** SPEED_EXPONENT
    reading_stars = 10.0 * reading_component ** 0.95
    rhythm_stars = 10.0 * rhythm_component ** 0.9
    stamina_stars = 10.0 * stamina_component ** 0.9
    technical_stars = 10.0 * technical_component ** 0.9

    overall = (
        aim_stars * WEIGHTS["aim"]
        + speed_stars * WEIGHTS["speed"]
        + reading_stars * WEIGHTS["reading"]
        + rhythm_stars * WEIGHTS["rhythm"]
        + stamina_stars * WEIGHTS["stamina"]
        + technical_stars * WEIGHTS["technical"]
    )

    breakdown = {
        "aimComponent": aim_component,
        "speedComponent": speed_component,
        "readingComponent": reading_component,
        "rhythmComponent": rhythm_component,
        "staminaComponent": stamina_component,
        "technicalComponent": technical_component,
        "speedExponent": SPEED_EXPONENT,
        "aimExponent": AIM_EXPONENT,
        "weights": dict(WEIGHTS),
    }

    return StarRating(
        overall=clamp(overall, 0.0, 10.0),
        aim=clamp(aim_stars, 0.0, 10.0),
        speed=clamp(speed_stars, 0.0, 10.0),
        reading=clamp(reading_stars, 0.0, 10.0),
        rhythm=clamp(rhythm_stars, 0.0, 10.0),
        stamina=clamp(stamina_stars, 0.0, 10.0),
        technical=clamp(technical_stars, 0.0, 10.0),
        breakdown=breakdown,
    )


def compute_technical_score(
    metrics: RawMetrics,
    patterns,
) -> float:
    """Technical difficulty from angle complexity, direction changes,
    slider complexity, and pattern variety."""
    if not patterns:
        return clamp(metrics.angle_complexity / 180.0, 0.0, 1.0)

    average_pattern_score = (
        sum(pattern.score for pattern in patterns) / len(patterns)
    )
    angle_component = clamp(metrics.angle_complexity / 150.0, 0.0, 1.0)
    direction_component = clamp(
        metrics.direction_change_count / max(1, metrics.object_count),
        0.0,
        0.5,
    )
    slider_component = metrics.slider_complexity
    pattern_component = clamp(average_pattern_score, 0.0, 1.0)

    return clamp(
        angle_component * 0.3
        + direction_component * 0.2
        + slider_component * 0.2
        + pattern_component * 0.3,
        0.0,
        1.0,
    )


def _speed_component(metrics: RawMetrics) -> float:
    density_component = clamp(metrics.objects_per_second / 3.5, 0.0, 1.0)
    velocity_component = clamp(metrics.average_cursor_velocity_pps / 900.0, 0.0, 1.0)
    stream_component = clamp(metrics.longest_stream_length / 8.0, 0.0, 1.0)
    burst_component = clamp(metrics.longest_burst_length / 5.0, 0.0, 1.0)
    return clamp(
        density_component * 0.4
        + velocity_component * 0.3
        + stream_component * 0.2
        + burst_component * 0.1,
        0.0,
        1.0,
    )

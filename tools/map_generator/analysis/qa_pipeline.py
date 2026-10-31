"""QA gate between generation and packaging.

Wraps :class:`~tools.map_generator.analysis.cursor_physics.AutoPlaySimulator`
into the single call the pipeline needs: measure the map, nerf anything a
cursor cannot physically reach, and re-measure so the reported star rating
describes the map that actually ships.
"""

from __future__ import annotations

from typing import Any

from .cursor_physics import MAX_CURSOR_VELOCITY_PX_PER_MS, AutoPlaySimulator


def run_qa(
    hit_objects: list[dict],
    *,
    max_velocity: float = MAX_CURSOR_VELOCITY_PX_PER_MS,
    auto_nerf: bool = True,
) -> dict[str, Any]:
    """Simulate playability and repair unplayable jumps in one pass.

    Args:
        hit_objects: Final object payloads (``to_dict()`` form), in play order.
        max_velocity: Cursor speed ceiling in pixels per millisecond.
        auto_nerf: When ``True``, jumps above the ceiling are clamped toward
            their predecessor and the map is simulated again.

    Returns:
        ``{"report": <simulation>, "objects": <payloads>, "nerfed": <count>}``.
        ``objects`` is always aligned 1:1 with the input.
    """
    simulator = AutoPlaySimulator(max_velocity=max_velocity)
    report = simulator.simulate_playthrough(hit_objects)

    if report["playable"] or not auto_nerf:
        return {"report": report, "objects": list(hit_objects), "nerfed": 0}

    nerfed_objects, nerfed_count = simulator.nerf_unplayable(hit_objects)
    repaired = simulator.simulate_playthrough(nerfed_objects)
    repaired["nerfedObjects"] = nerfed_count
    repaired["starRatingBeforeNerf"] = report["predictedStarRating"]
    return {"report": repaired, "objects": nerfed_objects, "nerfed": nerfed_count}

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ..config import DifficultyPreset
from ..variation import EventSelectionVariation, PositionVariation


@dataclass(frozen=True)
class CandidateGenerationProfile:
    index: int
    difficulty: str
    root_seed: int
    candidate_seed: int
    timing_variation_enabled: bool
    variation_signature: str
    event_variation: EventSelectionVariation
    position_variation: PositionVariation

    def variation_profile(self) -> dict[str, float | int | bool]:
        payload = self.position_variation.to_dict()
        payload.update(self.event_variation.to_dict())
        return payload

    def metadata_dict(self) -> dict[str, object]:
        return {
            "index": self.index,
            "difficulty": self.difficulty,
            "rootSeed": self.root_seed,
            "candidateSeed": self.candidate_seed,
            "timingVariationEnabled": self.timing_variation_enabled,
            "variationSignature": self.variation_signature,
            "variationProfile": self.variation_profile(),
        }


def build_candidate_profile(
    *,
    preset: DifficultyPreset,
    root_seed: int,
    candidate_index: int,
    timing_variation: bool,
) -> CandidateGenerationProfile:
    position_variation = PositionVariation(
        preferred_jump_distance_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "jump", _jump_amplitude(preset.name)
        ),
        pattern_variation_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "pattern", 0.18
        ),
        edge_penalty_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "edge", 0.16
        ),
        recent_position_penalty_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "recent", 0.14
        ),
        repetition_penalty_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "repeat", 0.14
        ),
        center_recovery_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "recover", 0.18
        ),
        energy_influence_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "energy", 0.16
        ),
        strength_influence_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "strength", 0.16
        ),
        arc_bias=_scaled_bias(root_seed, preset.name, candidate_index, "arc", 0.35),
        alternation_bias=_scaled_bias(root_seed, preset.name, candidate_index, "alternate", 0.35),
        continuation_bias=_scaled_bias(root_seed, preset.name, candidate_index, "continue", 0.35),
        triangle_bias=_scaled_bias(root_seed, preset.name, candidate_index, "triangle", 0.28),
        direction_jitter_multiplier=_scaled_multiplier(
            root_seed, preset.name, candidate_index, "jitter", 0.22
        ),
    )
    event_variation = EventSelectionVariation()
    if timing_variation:
        event_variation = EventSelectionVariation(
            onset_strength_offset=_scaled_bias(root_seed, preset.name, candidate_index, "onset", 0.04),
            beat_strength_offset=_scaled_bias(root_seed, preset.name, candidate_index, "beat", 0.03),
            strong_beat_offset=_scaled_bias(root_seed, preset.name, candidate_index, "strong", 0.04),
            target_gap_multiplier=_scaled_multiplier(
                root_seed, preset.name, candidate_index, "gap", 0.05
            ),
            merge_tolerance_offset_ms=int(
                round(_centered_value(root_seed, preset.name, candidate_index, "merge") * 8)
            ),
            weak_event_confidence_bias=_scaled_bias(
                root_seed, preset.name, candidate_index, "weak", 0.05
            ),
        )

    variation_signature = json.dumps(
        {
            "position": position_variation.to_dict(),
            "timing": event_variation.to_dict(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    candidate_seed = derive_candidate_seed(
        root_seed=root_seed,
        difficulty=preset.name,
        candidate_index=candidate_index,
        variation_signature=variation_signature,
    )

    return CandidateGenerationProfile(
        index=candidate_index,
        difficulty=preset.name,
        root_seed=root_seed,
        candidate_seed=candidate_seed,
        timing_variation_enabled=timing_variation,
        variation_signature=variation_signature,
        event_variation=event_variation,
        position_variation=position_variation,
    )


def derive_candidate_seed(
    *,
    root_seed: int,
    difficulty: str,
    candidate_index: int,
    variation_signature: str,
) -> int:
    digest = hashlib.blake2b(
        f"{root_seed}|{difficulty}|{candidate_index}|{variation_signature}".encode("utf-8"),
        digest_size=16,
    ).digest()
    seed = int.from_bytes(digest[:8], "big") % 2_147_483_647
    return seed if seed > 0 else 1


def _jump_amplitude(difficulty: str) -> float:
    if difficulty == "easy":
        return 0.08
    if difficulty == "normal":
        return 0.1
    return 0.12


def _scaled_multiplier(
    root_seed: int,
    difficulty: str,
    candidate_index: int,
    label: str,
    amplitude: float,
) -> float:
    return round(1.0 + _centered_value(root_seed, difficulty, candidate_index, label) * amplitude, 4)


def _scaled_bias(
    root_seed: int,
    difficulty: str,
    candidate_index: int,
    label: str,
    amplitude: float,
) -> float:
    return round(_centered_value(root_seed, difficulty, candidate_index, label) * amplitude, 4)


def _centered_value(
    root_seed: int,
    difficulty: str,
    candidate_index: int,
    label: str,
) -> float:
    digest = hashlib.blake2b(
        f"{root_seed}|{difficulty}|{candidate_index}|{label}".encode("utf-8"),
        digest_size=8,
    ).digest()
    integer = int.from_bytes(digest, "big")
    ratio = integer / float((1 << 64) - 1)
    return ratio * 2.0 - 1.0

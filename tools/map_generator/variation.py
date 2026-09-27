from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EventSelectionVariation:
    onset_strength_offset: float = 0.0
    beat_strength_offset: float = 0.0
    strong_beat_offset: float = 0.0
    target_gap_multiplier: float = 1.0
    merge_tolerance_offset_ms: int = 0
    weak_event_confidence_bias: float = 0.0
    allow_offbeat_onsets: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "onsetStrengthOffset": round(self.onset_strength_offset, 4),
            "beatStrengthOffset": round(self.beat_strength_offset, 4),
            "strongBeatOffset": round(self.strong_beat_offset, 4),
            "targetGapMultiplier": round(self.target_gap_multiplier, 4),
            "mergeToleranceOffsetMs": self.merge_tolerance_offset_ms,
            "weakEventConfidenceBias": round(self.weak_event_confidence_bias, 4),
        }
        if self.allow_offbeat_onsets is not None:
            payload["allowOffbeatOnsets"] = self.allow_offbeat_onsets
        return payload


@dataclass(frozen=True)
class PositionVariation:
    preferred_jump_distance_multiplier: float = 1.0
    pattern_variation_multiplier: float = 1.0
    edge_penalty_multiplier: float = 1.0
    recent_position_penalty_multiplier: float = 1.0
    repetition_penalty_multiplier: float = 1.0
    center_recovery_multiplier: float = 1.0
    energy_influence_multiplier: float = 1.0
    strength_influence_multiplier: float = 1.0
    arc_bias: float = 0.0
    alternation_bias: float = 0.0
    continuation_bias: float = 0.0
    triangle_bias: float = 0.0
    direction_jitter_multiplier: float = 1.0
    # Pattern intelligence variation fields (Phase 10)
    pattern_switch_bias: float = 0.0
    burst_bias: float = 0.0
    stream_bias: float = 0.0
    zigzag_bias: float = 0.0
    wave_bias: float = 0.0
    fan_bias: float = 0.0
    spiral_bias: float = 0.0
    flow_comfort_weight: float = 1.0
    novelty_weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "jumpDistanceMultiplier": round(self.preferred_jump_distance_multiplier, 4),
            "patternVariationMultiplier": round(self.pattern_variation_multiplier, 4),
            "edgePenaltyMultiplier": round(self.edge_penalty_multiplier, 4),
            "recentPositionPenaltyMultiplier": round(self.recent_position_penalty_multiplier, 4),
            "repetitionPenaltyMultiplier": round(self.repetition_penalty_multiplier, 4),
            "centerRecoveryMultiplier": round(self.center_recovery_multiplier, 4),
            "energyInfluenceMultiplier": round(self.energy_influence_multiplier, 4),
            "strengthInfluenceMultiplier": round(self.strength_influence_multiplier, 4),
            "arcBias": round(self.arc_bias, 4),
            "alternationBias": round(self.alternation_bias, 4),
            "continuationBias": round(self.continuation_bias, 4),
            "triangleBias": round(self.triangle_bias, 4),
            "directionJitterMultiplier": round(self.direction_jitter_multiplier, 4),
            "patternSwitchBias": round(self.pattern_switch_bias, 4),
            "burstBias": round(self.burst_bias, 4),
            "streamBias": round(self.stream_bias, 4),
            "zigzagBias": round(self.zigzag_bias, 4),
            "waveBias": round(self.wave_bias, 4),
            "fanBias": round(self.fan_bias, 4),
            "spiralBias": round(self.spiral_bias, 4),
            "flowComfortWeight": round(self.flow_comfort_weight, 4),
            "noveltyWeight": round(self.novelty_weight, 4),
        }

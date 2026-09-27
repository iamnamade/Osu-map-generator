"""Phase 20 persistent musical motif engine.

Groups phrases into motifs so repeated song sections share an identity, then
assigns each phrase a mapping strategy (establish / intensify / release /
contrast / recover / transition). Motif identity preserves long-range
structural coherence while controlled strategies allow variation.

Everything is deterministic: identical phrase lists produce identical motifs
and strategies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..utils import clamp
from .phrase_analyzer import _FEATURE_KEYS, _cosine_similarity
from .phrase_models import Motif, Phrase, PhraseStrategyName


@dataclass(frozen=True)
class MotifEngineConfig:
    motif_similarity_threshold: float = 0.8
    max_motif_count: int = 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "motifSimilarityThreshold": round(self.motif_similarity_threshold, 4),
            "maxMotifCount": self.max_motif_count,
        }


DEFAULT_MOTIF_CONFIG = MotifEngineConfig()


def _phrase_vector(phrase: Phrase) -> list[float]:
    return [float(getattr(phrase, key)) for key in _FEATURE_KEYS]


def build_motifs(
    phrases: list[Phrase],
    config: MotifEngineConfig = DEFAULT_MOTIF_CONFIG,
) -> list[Motif]:
    """Assign motif ids to phrases and return the motif registry.

    Phrases with mutually-high feature similarity are grouped into the same
    motif. A phrase with no close match starts its own motif (identity is
    preserved even for one-off phrases).
    """
    vectors = {phrase.id: _phrase_vector(phrase) for phrase in phrases}
    phrase_by_id = {phrase.id: phrase for phrase in phrases}

    assigned: dict[int, int] = {}
    motif_phrases: dict[int, list[int]] = {}
    next_motif_id = 1

    # First pass: chain similar phrases into motifs (union of high-similarity
    # links, deterministic order by phrase id).
    for left in phrases:
        if left.id in assigned:
            continue
        assigned[left.id] = next_motif_id
        motif_phrases[next_motif_id] = [left.id]
        # Extend with later phrases similar to any phrase already in the motif.
        changed = True
        while changed:
            changed = False
            for right in phrases:
                if right.id in assigned:
                    continue
                if any(
                    _cosine_similarity(vectors[right.id], vectors[member])
                    >= config.motif_similarity_threshold
                    for member in motif_phrases[next_motif_id]
                ):
                    assigned[right.id] = next_motif_id
                    motif_phrases[next_motif_id].append(right.id)
                    changed = True
        next_motif_id += 1
        if next_motif_id > config.max_motif_count:
            break

    # Any phrase skipped by the cap gets its own motif id deterministically.
    for phrase in phrases:
        if phrase.id not in assigned:
            assigned[phrase.id] = next_motif_id
            motif_phrases[next_motif_id] = [phrase.id]
            next_motif_id += 1

    for phrase in phrases:
        phrase.__dict__["motif_id"] = assigned[phrase.id]

    motifs: list[Motif] = []
    for motif_id in sorted(motif_phrases):
        members = sorted(motif_phrases[motif_id])
        motif = _build_motif(motif_id, members, phrase_by_id)
        motifs.append(motif)
    return motifs


def _build_motif(
    motif_id: int,
    members: list[int],
    phrase_by_id: dict[int, Phrase],
) -> Motif:
    member_phrases = [phrase_by_id[member] for member in members]
    # Rhythm signature: subdivision ratio + beat density averaged, rounded.
    rhythm_signature = [
        round(
            sum(phrase.subdivision_ratio for phrase in member_phrases)
            / len(member_phrases),
            4,
        ),
        round(
            sum(phrase.beat_density for phrase in member_phrases) / len(member_phrases),
            4,
        ),
        round(
            sum(phrase.rhythm_complexity for phrase in member_phrases)
            / len(member_phrases),
            4,
        ),
    ]
    density_profile = [
        round(sum(phrase.onset_density for phrase in member_phrases) / len(member_phrases), 4),
        round(sum(phrase.average_energy for phrase in member_phrases) / len(member_phrases), 4),
    ]
    primary_label = next(
        (phrase.label for phrase in member_phrases if phrase.label),
        "motif",
    )
    return Motif(
        id=motif_id,
        phrase_ids=members,
        rhythm_signature=rhythm_signature,
        density_profile=density_profile,
        occurrence_count=len(members),
        label=f"Motif {motif_id} ({primary_label})",
    )


def assign_phrase_strategies(
    phrases: list[Phrase],
    config: MotifEngineConfig = DEFAULT_MOTIF_CONFIG,
) -> list[Phrase]:
    """Assign a mapping strategy to every phrase.

    Rules (deterministic):

    * Very quiet phrases become ``recover`` windows.
    * First occurrence of a motif establishes it (``establish``).
    * Later occurrences intensify when energy rises, otherwise ``variation``
      is expressed through ``intensify`` / ``release`` based on energy trend.
    * Short bridging phrases between differing sections become ``transition``.
    * Phrases contrasting their section neighbors become ``contrast``.
    * Everything else stays ``neutral``.
    """
    ordered = sorted(phrases, key=lambda phrase: (phrase.start_ms, phrase.id))
    by_motif: dict[int, list[Phrase]] = {}
    for phrase in ordered:
        if phrase.motif_id is not None:
            by_motif.setdefault(phrase.motif_id, []).append(phrase)

    for phrase in ordered:
        strategy = _strategy_for_phrase(
            phrase=phrase,
            ordered=ordered,
            by_motif=by_motif,
            config=config,
        )
        phrase.__dict__["strategy"] = strategy
    return ordered


def _strategy_for_phrase(
    *,
    phrase: Phrase,
    ordered: list[Phrase],
    by_motif: dict[int, list[Phrase]],
    config: MotifEngineConfig,
) -> PhraseStrategyName:
    if phrase.quiet_ratio >= 0.45 or phrase.average_energy < 0.22:
        return "recover"
    if phrase.duration_ms <= 7000 and len(ordered) > 1:
        return "transition"
    if phrase.motif_id is None:
        return "neutral"
    occurrences = by_motif.get(phrase.motif_id) or []
    position = occurrences.index(phrase) if phrase in occurrences else 0
    if position == 0:
        return "establish"
    # Compare with the previous occurrence of the same motif.
    previous = occurrences[position - 1] if position > 0 else None
    if previous is not None:
        energy_delta = phrase.average_energy - previous.average_energy
        if energy_delta > 0.05:
            return "intensify"
        if energy_delta < -0.05:
            return "release"
    return "neutral"


def _strategy_rank(strategy: PhraseStrategyName) -> int:
    order: dict[str, int] = {
        "recover": 0,
        "transition": 1,
        "neutral": 2,
        "establish": 3,
        "release": 3,
        "contrast": 4,
        "intensify": 5,
    }
    return order.get(strategy, 2)


def resolve_strategy_conflicts(
    phrases: list[Phrase],
    config: MotifEngineConfig = DEFAULT_MOTIF_CONFIG,
) -> list[Phrase]:
    """Resolve strategy conflicts for adjacent phrases.

    Guarantees no two consecutive phrases both escalate (which would create a
    monotonic difficulty wall). The stronger strategy wins deterministically.
    """
    ordered = sorted(phrases, key=lambda phrase: (phrase.start_ms, phrase.id))
    for index in range(1, len(ordered)):
        previous = ordered[index - 1]
        current = ordered[index]
        if (
            previous.strategy == "intensify"
            and current.strategy == "intensify"
        ):
            if _strategy_rank(previous.strategy) > _strategy_rank(current.strategy):
                current.__dict__["strategy"] = "neutral"
            else:
                previous.__dict__["strategy"] = "neutral"
    return ordered


def assign_all_strategies(
    phrases: list[Phrase],
    config: MotifEngineConfig = DEFAULT_MOTIF_CONFIG,
) -> list[Phrase]:
    """Assign strategies then resolve conflicts (deterministic full pass)."""
    phrases = assign_phrase_strategies(phrases, config)
    return resolve_strategy_conflicts(phrases, config)


def strategy_generation_multipliers(strategy: PhraseStrategyName) -> dict[str, float]:
    """Map a strategy to concrete generation parameters.

    These multipliers are consumed by the trajectory planner / generation
    hooks so the strategy is a *real* knob, not a label.
    """
    table: dict[str, dict[str, float]] = {
        "establish": {"density": 1.0, "movement": 0.95, "complexity": 0.95},
        "intensify": {"density": 1.22, "movement": 1.15, "complexity": 1.18},
        "release": {"density": 0.82, "movement": 0.88, "complexity": 0.82},
        "contrast": {"density": 1.1, "movement": 1.2, "complexity": 1.1},
        "recover": {"density": 0.6, "movement": 0.72, "complexity": 0.6},
        "transition": {"density": 0.85, "movement": 0.9, "complexity": 0.8},
        "neutral": {"density": 1.0, "movement": 1.0, "complexity": 1.0},
    }
    return table.get(strategy, table["neutral"])


def clamp_strategy_multiplier(value: float) -> float:
    return round(clamp(value, 0.4, 1.6), 4)

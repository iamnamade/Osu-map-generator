"""Second-order Markov model of a mapper's pattern style.

Learns ``P(next_state | previous_state, current_state)`` from corpus state
sequences, then samples styles forward.  This is the "mapper persona": the
model encodes which rhythm gap, spacing and turn a specific mapper tends to
use next *given the last two objects*, rather than a hand-tuned heuristic.

Storage
-------
During :meth:`MapperPersonaModel.train` successors are accumulated as plain
``dict`` keys of ``tuple[state_n_minus_1, state_n] -> list[state_n_plus_1]``,
which is the natural shape for counting.

For sampling that layout is converted once into integer-indexed numpy arrays:
each key maps to ``(indices, probabilities)`` where repeated successors have
already been folded into empirical frequencies.  A prediction is then a single
``Generator.choice`` call on preallocated arrays -- no per-prediction
recounting of successors, and no Python-level scan of the successor list.

Fallback ladder
---------------
A 2nd-order key is sparse: a corpus can easily never contain the exact pair of
states a generation run reaches.  Predictions therefore degrade in stages:

1. 2nd order -- the exact ``(previous, current)`` pair.
2. 1st order -- ignore ``previous`` and use ``current`` alone.
3. Uniform -- any state seen during training.

Each stage is only consulted when the previous one has no entry, so the model
always returns a state once it has seen any training data at all.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np

from .corpus_parser import PatternState

StateLike = PatternState | tuple[float, float, int]


def _as_state(value: StateLike | None) -> PatternState | None:
    """Normalise a plain tuple into a :class:`PatternState`."""
    if value is None:
        return None
    if isinstance(value, PatternState):
        return value
    return PatternState(value[0], value[1], value[2])


class MapperPersonaModel:
    """A learned, samplable model of one mapper's cursor and rhythm habits.

    Parameters
    ----------
    seed:
        Seed for the sampling RNG.  Two models trained on the same corpus with
        the same seed produce identical predictions, which keeps generated maps
        reproducible like the rest of the generator.
    """

    def __init__(self, *, seed: int | None = None) -> None:
        self._rng = np.random.default_rng(seed)

        #: 2nd-order transitions: ``(state_n-1, state_n) -> [state_n+1, ...]``.
        self.transitions: dict[tuple[PatternState, PatternState], list[PatternState]] = {}
        #: 1st-order transitions: ``state_n -> [state_n+1, ...]``.
        self.first_order: dict[PatternState, list[PatternState]] = {}
        #: States that opened a corpus sequence, used to seed generation.
        self._starts: dict[PatternState, int] = {}

        # Index-encoded sampling tables, rebuilt by ``_rebuild_tables``.
        self._states: list[PatternState] = []
        self._state_index: dict[PatternState, int] = {}
        self._second_table: dict[
            tuple[PatternState, PatternState], tuple[np.ndarray, np.ndarray]
        ] = {}
        self._first_table: dict[PatternState, tuple[np.ndarray, np.ndarray]] = {}
        self._uniform_indices = np.empty(0, dtype=np.int64)

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(self, sequences: Iterable[Sequence[StateLike]]) -> "MapperPersonaModel":
        """Learn transition frequencies from corpus state sequences.

        Retraining replaces any previous tables rather than accumulating, so
        repeated calls are idempotent for a given corpus.
        """
        self.transitions = {}
        self.first_order = {}
        self._starts = {}

        for sequence in sequences:
            states = [state for state in (_as_state(item) for item in sequence) if state is not None]
            if not states:
                continue

            self._starts[states[0]] = self._starts.get(states[0], 0) + 1

            for index in range(len(states) - 1):
                self.first_order.setdefault(states[index], []).append(states[index + 1])

            for index in range(len(states) - 2):
                key = (states[index], states[index + 1])
                self.transitions.setdefault(key, []).append(states[index + 2])

        self._rebuild_tables()
        return self

    def _rebuild_tables(self) -> None:
        """Fold successor lists into index arrays with empirical probabilities."""
        known: set[PatternState] = set(self.first_order)
        known.update(self._starts)
        for key, successors in self.transitions.items():
            known.update(key)
            known.update(successors)
        for successors in self.first_order.values():
            known.update(successors)

        # Sorted so indices (and therefore seeded sampling) are stable.
        self._states = sorted(known)
        self._state_index = {state: index for index, state in enumerate(self._states)}
        self._second_table = {}
        self._first_table = {}

        for key, successors in self.transitions.items():
            self._second_table[key] = self._build_distribution(successors)
        for state, successors in self.first_order.items():
            self._first_table[state] = self._build_distribution(successors)

        self._uniform_indices = np.arange(len(self._states), dtype=np.int64)

    def _build_distribution(
        self, successors: Sequence[PatternState]
    ) -> tuple[np.ndarray, np.ndarray]:
        counts: dict[PatternState, int] = {}
        for state in successors:
            counts[state] = counts.get(state, 0) + 1

        indices = np.fromiter(
            (self._state_index[state] for state in counts),
            dtype=np.int64,
            count=len(counts),
        )
        frequencies = np.fromiter(counts.values(), dtype=np.float64, count=len(counts))
        probabilities = frequencies / frequencies.sum()
        return indices, probabilities

    # ------------------------------------------------------------------
    # Prediction
    # ------------------------------------------------------------------
    def predict_next_state(
        self,
        current_state: StateLike | None,
        previous_state: StateLike | None,
    ) -> PatternState:
        """Sample the most plausible next state for this two-state context.

        Falls back from the 2nd-order key to the 1st-order key, then to a
        uniform draw over every state seen in training.
        """
        if not self._states:
            raise ValueError("MapperPersonaModel has no training data; call train() first.")

        current = _as_state(current_state)
        previous = _as_state(previous_state)

        if current is not None and previous is not None:
            entry = self._second_table.get((previous, current))
            if entry is not None:
                return self._sample(entry)

        if current is not None:
            entry = self._first_table.get(current)
            if entry is not None:
                return self._sample(entry)

        return self._sample((self._uniform_indices, None))

    def _sample(self, entry: tuple[np.ndarray, np.ndarray | None]) -> PatternState:
        indices, probabilities = entry
        if probabilities is None:
            chosen = int(self._rng.choice(indices))
        else:
            chosen = int(self._rng.choice(indices, p=probabilities))
        return self._states[chosen]

    def sample_initial_state(self) -> PatternState:
        """Pick a sequence-opening state, weighted by how often each occurred."""
        if not self._states:
            raise ValueError("MapperPersonaModel has no training data; call train() first.")

        if not self._starts:
            return self._sample((self._uniform_indices, None))

        states = list(self._starts)
        weights = np.fromiter(
            (self._starts[state] for state in states), dtype=np.float64, count=len(states)
        )
        probabilities = weights / weights.sum()
        chosen = int(self._rng.choice(len(states), p=probabilities))
        return states[chosen]

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def state_count(self) -> int:
        """Number of distinct states seen in training."""
        return len(self._states)

    @property
    def transition_count(self) -> int:
        """Number of distinct 2nd-order context keys."""
        return len(self._second_table)

    @property
    def states(self) -> list[PatternState]:
        """A copy of the sorted state vocabulary."""
        return list(self._states)

    def summary(self) -> dict[str, int]:
        """Compact description of the learned model."""
        return {
            "states": self.state_count,
            "secondOrderTransitions": self.transition_count,
            "firstOrderTransitions": len(self._first_table),
            "initialStates": len(self._starts),
            "observations": sum(len(items) for items in self.transitions.values()),
        }

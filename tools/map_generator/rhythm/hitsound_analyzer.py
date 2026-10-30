"""Multi-band percussive transient classification for smart hitsounding.

The analyzer splits the source audio into three frequency bands, detects
percussive onsets inside each band *independently*, and maps the bands onto
osu! hitsound bitmask bits:

    ==========  =======================  =====================  ======
    Band        Frequency range          Percussive target      Bit
    ==========  =======================  =====================  ======
    Low         ``< 250 Hz``             kick drum              ``4`` (Finish)
    Mid-high    ``1000 - 4000 Hz``       snare / clap           ``8`` (Clap)
    High        ``> 4000 Hz``            cymbal / hi-hat        ``2`` (Whistle)
    ==========  =======================  =====================  ======

The bitmask is built with bitwise OR, so a hit that lands on a kick *and* a
hi-hat yields ``4 | 2 == 6``.  A hit that matches no band yields ``0``, which
is osu!'s plain Normal sample (the format default, not a distinct sound).

Detection model
--------------
Each band gets its own onset-strength envelope: the half-wave rectified
first difference of the band's mean STFT magnitude.  That is band-limited
spectral flux, computed with numpy on the whole track at once (no per-sample
Python loop).  ``librosa.onset.onset_detect`` then peak-picks each band
envelope separately, so a snare's 2 kHz burst cannot mask a simultaneous
kick.

Lookup cost
-----------
Onset timestamps are stored as sorted ``float64`` arrays.  A query is one
``np.searchsorted`` plus two distance checks -- O(log n) in the number of
onsets in that band, with no Python-level scanning of the onset list, which
keeps per-object lookups far below the 5 ms budget.

Timing accuracy
---------------
The STFT hop is deliberately finer (512) than the project's beat-analysis hop
(1024, ~46 ms).  Quantising hitsound timestamps to the beat grid costs more
accuracy than the shared grid buys: on a synthetic kick/snare/hat probe the
finer hop resolves every band to within 25 ms, while the oversampled grid
misses the mid band because its 46 ms frame quantisation alone exceeds the
match tolerance.

Band flux peaks are reported up to half an analysis window early, because a
centered STFT starts capturing a transient as soon as the window reaches it.
``window_latency_ms`` adds that half-window back.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from librosa import fft_frequencies as librosa_fft_frequencies
from librosa import frames_to_time as librosa_frames_to_time
from librosa import onset as librosa_onset
from librosa import stft as librosa_stft

#: osu! hitsound bitmask bits (see the .osu [HitObjects] hitSound field).
HITSOUND_NORMAL = 0
HITSOUND_WHISTLE = 2
HITSOUND_FINISH = 4
HITSOUND_CLAP = 8

#: Band edges in Hz.  The 250-1000 Hz gap is deliberate: that range carries
#: most melodic/vocal content and only muddies percussive classification.
LOW_BAND_MAX_HZ = 250.0
MID_BAND_MIN_HZ = 1_000.0
MID_BAND_MAX_HZ = 4_000.0
HIGH_BAND_MIN_HZ = 4_000.0

#: Default STFT window and hop.  A hop of 512 (~23 ms at 22.05 kHz) is finer
#: than the project's 1024 beat-analysis hop so hitsound timestamps are not
#: quantised to the beat grid.
DEFAULT_N_FFT = 2_048
DEFAULT_HOP_LENGTH = 512

#: Band name -> bit it contributes to the hitsound mask.
BAND_BITS: tuple[tuple[str, int], ...] = (
    ("low", HITSOUND_FINISH),
    ("mid_high", HITSOUND_CLAP),
    ("high", HITSOUND_WHISTLE),
)


class HitsoundAnalyzer:
    """Classify percussive transients and resolve osu! hitsound bitmasks.

    Parameters
    ----------
    audio_path:
        Path to the source audio file.  Kept for diagnostics and used to load
        the audio when predecoded samples are not supplied.
    samples:
        Optional pre-loaded mono samples.  Passing the samples the generator
        already decoded avoids a second full-file decode.
    sample_rate:
        Sample rate of ``samples``.  Ignored when ``samples`` is ``None``.
    hop_length:
        STFT hop used for band separation.  Defaults to a hop finer than the
        project's beat-analysis hop so onset timestamps keep sub-beat
        resolution.
    """

    def __init__(
        self,
        audio_path: str,
        *,
        samples: np.ndarray | None = None,
        sample_rate: int | None = None,
        n_fft: int = DEFAULT_N_FFT,
        hop_length: int | None = None,
    ) -> None:
        self.audio_path = Path(audio_path)
        self.n_fft = n_fft

        if samples is None:
            # Imported lazily so this module stays importable without pulling
            # the whole analysis stack (and its optional FFmpeg hinting).
            from ..audio_analyzer import _load_audio

            y, resolved_rate = _load_audio(self.audio_path)
        else:
            y = np.asarray(samples, dtype=np.float32)
            resolved_rate = int(sample_rate or 0)
            if resolved_rate <= 0:
                raise ValueError("sample_rate is required when samples are supplied.")

        self.sample_rate = int(resolved_rate)
        if y.ndim > 1:
            y = np.mean(y, axis=0).astype(np.float32, copy=False)
        self.samples = y

        self.hop_length = int(DEFAULT_HOP_LENGTH if hop_length is None else hop_length)

        # A centered STFT reports a transient up to half a window early, so
        # compensate by that much when converting flux peaks to timestamps.
        self.window_latency_ms = (self.n_fft / 2.0) / float(self.sample_rate) * 1_000.0

        # Band onset timestamps, sorted ascending, in milliseconds.
        self._band_onsets_ms: dict[str, np.ndarray] = self._detect_band_onsets()

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------
    def _detect_band_onsets(self) -> dict[str, np.ndarray]:
        y = self.samples
        if y.size == 0:
            return {name: np.empty(0, dtype=np.float64) for name, _ in BAND_BITS}

        # librosa's STFT needs at least one full window; pad short clips.
        if y.size < self.n_fft:
            y = np.pad(y, (0, self.n_fft - y.size))

        magnitude = np.abs(
            librosa_stft(y=y, n_fft=self.n_fft, hop_length=self.hop_length)
        )
        frequencies = librosa_fft_frequencies(sr=self.sample_rate, n_fft=self.n_fft)

        masks = (
            frequencies < LOW_BAND_MAX_HZ,
            (frequencies >= MID_BAND_MIN_HZ) & (frequencies < MID_BAND_MAX_HZ),
            frequencies >= HIGH_BAND_MIN_HZ,
        )

        onsets: dict[str, np.ndarray] = {}
        for (name, _bit), mask in zip(BAND_BITS, masks):
            if not bool(np.any(mask)):
                onsets[name] = np.empty(0, dtype=np.float64)
                continue

            # Mean magnitude per bin keeps a wide band from dominating a
            # narrow one purely because it holds more STFT bins.
            band_energy = magnitude[mask, :].mean(axis=0)

            # Band-limited spectral flux: half-wave rectified difference.
            envelope = np.diff(band_energy, prepend=band_energy[:1])
            np.maximum(envelope, 0.0, out=envelope)

            peak = float(np.max(envelope)) if envelope.size else 0.0
            if peak <= 1e-9:
                onsets[name] = np.empty(0, dtype=np.float64)
                continue

            frames = librosa_onset.onset_detect(
                onset_envelope=envelope,
                sr=self.sample_rate,
                hop_length=self.hop_length,
                units="frames",
                backtrack=False,
            )
            times_ms = librosa_frames_to_time(
                frames if frames is not None else np.empty(0, dtype=int),
                sr=self.sample_rate,
                hop_length=self.hop_length,
            )
            # Onsets are already monotonic across frames; sort defensively so
            # searchsorted stays valid.  The half-window latency is added back
            # so the timestamp marks the transient, not the window edge.
            onsets[name] = np.sort(
                np.asarray(times_ms, dtype=np.float64) * 1_000.0 + self.window_latency_ms
            )

        return onsets

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------
    @staticmethod
    def _has_onset_near(onsets_ms: np.ndarray, time_ms: float, tolerance_ms: float) -> bool:
        """Return True when any onset lies within ``tolerance_ms`` of ``time_ms``."""
        if onsets_ms.size == 0:
            return False

        # Nearest candidates are the insertion point and its left neighbour.
        index = int(np.searchsorted(onsets_ms, time_ms))
        best = np.inf
        if index < onsets_ms.size:
            best = float(abs(onsets_ms[index] - time_ms))
        if index > 0 and best > tolerance_ms:
            left = float(abs(onsets_ms[index - 1] - time_ms))
            if left < best:
                best = left
        return best <= tolerance_ms

    def get_hitsound_bitmask(self, time_ms: float, tolerance_ms: float = 25.0) -> int:
        """Build the osu! hitsound bitmask for a hit at ``time_ms``.

        Each band that has a detected onset within ``tolerance_ms`` of
        ``time_ms`` contributes its bit via bitwise OR.  Returns ``0``
        (Normal) when nothing matches.
        """
        mask = HITSOUND_NORMAL
        for name, bit in BAND_BITS:
            if self._has_onset_near(self._band_onsets_ms[name], float(time_ms), tolerance_ms):
                mask |= bit
        return mask

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def band_onset_times_ms(self, band: str) -> np.ndarray:
        """Return the detected onset timestamps for ``band`` in milliseconds."""
        try:
            return self._band_onsets_ms[band].copy()
        except KeyError as error:
            valid = ", ".join(name for name, _ in BAND_BITS)
            raise KeyError(f"Unknown band {band!r}; expected one of: {valid}") from error

    def onset_counts(self) -> dict[str, int]:
        """Number of detected onsets per band (useful for reporting)."""
        return {name: int(self._band_onsets_ms[name].size) for name, _ in BAND_BITS}

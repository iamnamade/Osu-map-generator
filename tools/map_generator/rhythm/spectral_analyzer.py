"""Spectral foundation for the generative pipeline.

This is the audio side of the engine: one loaded track, queried by timestamp.
Placement asks :meth:`AudioEngine.intensity_at` how loud a passage is so jump
distances can breathe with the music, and asks :meth:`AudioEngine.get_hitsound`
which percussive transient is on a given hit so the right sample plays.

Intensity model
---------------
Two complementary cues are extracted per STFT frame:

* **RMS energy** -- how loud the passage is overall (drops and kiai).
* **Spectral flux** -- how fast the spectrum is changing (transient density).

Each is normalised against its own 5th/95th percentile so a quiet master and a
loud master produce comparable results, then blended (energy weighted higher,
because loudness tracks the verse/drop distinction better than change does) and
mapped onto ``[0.5, 2.0]``: ``0.5`` is a verse, ``1.0`` is neutral, ``2.0`` is a
drop.  Normalising by percentile rather than by max keeps a single clipped
sample from flattening the whole curve.

Percussive bands
----------------
Three-band transient classification already exists in
:class:`~tools.map_generator.rhythm.hitsound_analyzer.HitsoundAnalyzer` --
low (<250 Hz, kick, bit ``4``), mid-high (1-4 kHz, snare, bit ``8``) and high
(>4 kHz, cymbal, bit ``2``).  This engine owns that analyser rather than
re-implementing the STFT masks: the band split is subtle (hop sizing, half
window latency compensation) and duplicating it would let the two drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from librosa import feature as librosa_feature
from librosa import frames_to_time as librosa_frames_to_time
from librosa import load as librosa_load
from librosa import stft as librosa_stft

from .hitsound_analyzer import HitsoundAnalyzer

#: Frame curve bounds. 1.0 is neutral, so an unanalysable track leaves
#: placement untouched.
MIN_INTENSITY = 0.5
MAX_INTENSITY = 2.0

#: Blend weights between loudness and change. Energy dominates because it maps
#: onto the verse/drop distinction directly; flux only sharpens busy passages.
RMS_WEIGHT = 0.65
FLUX_WEIGHT = 0.35

#: STFT settings. The hop matches the hitsound analyser so both views of the
#: track share a time grid.
DEFAULT_N_FFT = 2_048
DEFAULT_HOP_LENGTH = 512

#: Percentiles used for robust per-cue normalisation.
LOW_PERCENTILE = 5.0
HIGH_PERCENTILE = 95.0


class AudioEngine:
    """Loaded audio with timestamp-addressed intensity and hitsound queries.

    Parameters
    ----------
    audio_path:
        Source track. Only read when ``samples`` is not supplied.
    samples:
        Pre-decoded mono samples, so callers that already loaded the track do
        not pay for a second decode.
    sample_rate:
        Sample rate of ``samples``; required with pre-decoded samples.
    """

    def __init__(
        self,
        audio_path: str | Path,
        *,
        samples: np.ndarray | None = None,
        sample_rate: int | None = None,
        n_fft: int = DEFAULT_N_FFT,
        hop_length: int = DEFAULT_HOP_LENGTH,
    ) -> None:
        self.audio_path = Path(audio_path)
        self.n_fft = int(n_fft)
        self.hop_length = int(hop_length)

        if samples is None:
            y, resolved_rate = librosa_load(
                self.audio_path.as_posix(), sr=None, mono=True
            )
        else:
            y = np.asarray(samples, dtype=np.float32)
            resolved_rate = int(sample_rate or 0)
            if resolved_rate <= 0:
                raise ValueError("sample_rate is required when samples are supplied.")

        if np.asarray(y).ndim > 1:
            y = np.mean(np.asarray(y), axis=0)
        self.samples = np.asarray(y, dtype=np.float32)
        self.sample_rate = int(resolved_rate)

        self._frame_count = 0
        self._frame_times_ms = np.empty(0, dtype=np.float64)
        self._intensity = np.empty(0, dtype=np.float64)

        # Band onsets come from the existing three-band analyser.
        self._hitsounds = HitsoundAnalyzer(
            self.audio_path.as_posix(),
            samples=self.samples,
            sample_rate=self.sample_rate,
            n_fft=self.n_fft,
            hop_length=self.hop_length,
        )

        self._intensity = self.compute_intensity()

    # ------------------------------------------------------------------
    # Intensity
    # ------------------------------------------------------------------
    def compute_intensity(self) -> np.ndarray:
        """Build the normalised intensity curve, one value per STFT frame.

        Returns the curve in ``[MIN_INTENSITY, MAX_INTENSITY]`` and caches it;
        call :meth:`intensity_at` for a single timestamp.
        """
        samples = self.samples
        if samples.size == 0:
            self._frame_times_ms = np.empty(0, dtype=np.float64)
            self._frame_count = 0
            return np.empty(0, dtype=np.float64)

        # librosa needs a full window; pad short clips so the curve still exists.
        if samples.size < self.n_fft:
            samples = np.pad(samples, (0, self.n_fft - samples.size))

        magnitude = np.abs(
            librosa_stft(y=samples, n_fft=self.n_fft, hop_length=self.hop_length)
        )
        self._frame_count = int(magnitude.shape[1])
        self._frame_times_ms = (
            librosa_frames_to_time(
                np.arange(self._frame_count),
                sr=self.sample_rate,
                hop_length=self.hop_length,
            )
            * 1_000.0
        )

        rms = librosa_feature.rms(y=samples, frame_length=self.n_fft, hop_length=self.hop_length)[0]
        # Spectral flux: half-wave rectified frame-to-frame change, summed over bins.
        flux = np.zeros(self._frame_count, dtype=np.float64)
        if self._frame_count > 1:
            flux[1:] = np.sum(np.maximum(np.diff(magnitude, axis=1), 0.0), axis=0)

        loudness = _normalise(rms[: self._frame_count])
        change = _normalise(flux)
        blended = np.clip(RMS_WEIGHT * loudness + FLUX_WEIGHT * change, 0.0, 1.0)
        curve = MIN_INTENSITY + (MAX_INTENSITY - MIN_INTENSITY) * blended
        return curve.astype(np.float64, copy=False)

    def intensity_at(self, time_ms: float) -> float:
        """Normalised intensity multiplier at ``time_ms``, in ``[0.5, 2.0]``.

        Returns ``1.0`` (neutral) when the track is empty or unanalysed, so
        placement behaves exactly as it did without an engine attached.
        """
        if self._intensity.size == 0:
            return 1.0
        index = int(np.searchsorted(self._frame_times_ms, float(time_ms), side="right")) - 1
        index = max(0, min(index, self._intensity.size - 1))
        return float(np.clip(self._intensity[index], MIN_INTENSITY, MAX_INTENSITY))

    # ------------------------------------------------------------------
    # Percussion
    # ------------------------------------------------------------------
    def extract_onsets(self) -> dict[str, np.ndarray]:
        """Detected onset timestamps per band, in milliseconds.

        Keys are ``low`` (<250 Hz), ``mid`` (1-4 kHz) and ``high`` (>4 kHz).
        """
        return {
            "low": self._hitsounds.band_onset_times_ms("low"),
            "mid": self._hitsounds.band_onset_times_ms("mid_high"),
            "high": self._hitsounds.band_onset_times_ms("high"),
        }

    def get_hitsound(self, time_ms: float) -> int:
        """osu! hitsound bitmask for a hit at ``time_ms`` (4 kick / 8 snare / 2 cymbal)."""
        return int(self._hitsounds.get_hitsound_bitmask(float(time_ms)))

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def duration_ms(self) -> float:
        """Track length in milliseconds."""
        if self.sample_rate <= 0:
            return 0.0
        return self.samples.size / float(self.sample_rate) * 1_000.0

    def summary(self) -> dict[str, Any]:
        """Compact description of the analysis, useful for diagnostics."""
        counts = self._hitsounds.onset_counts()
        return {
            "sampleRate": self.sample_rate,
            "durationMs": round(self.duration_ms, 1),
            "frames": self._frame_count,
            "intensityMin": round(float(self._intensity.min()), 3) if self._intensity.size else 1.0,
            "intensityMax": round(float(self._intensity.max()), 3) if self._intensity.size else 1.0,
            "onsets": {
                "low": counts.get("low", 0),
                "mid": counts.get("mid_high", 0),
                "high": counts.get("high", 0),
            },
        }


def _normalise(values: np.ndarray) -> np.ndarray:
    """Percentile-normalise ``values`` into 0..1, tolerating flat signals."""
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0:
        return np.empty(0, dtype=np.float64)
    low, high = np.percentile(array, [LOW_PERCENTILE, HIGH_PERCENTILE])
    span = float(high - low)
    if span <= 1e-9:
        return np.zeros_like(array)
    return np.clip((array - low) / span, 0.0, 1.0)

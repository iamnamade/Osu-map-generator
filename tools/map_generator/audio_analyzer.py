from __future__ import annotations

from pathlib import Path

import librosa
import numpy as np

from .models import AudioAnalysis, EnergyFrame, EnergyRegion, KiaiSection, TimedStrength
from .utils import MapGeneratorError, clamp, ensure_existing_file, is_ffmpeg_available, round_ms

ANALYSIS_SAMPLE_RATE = 22_050
FRAME_LENGTH = 2_048
HOP_LENGTH = 1_024
MIN_AUDIO_DURATION_MS = 2_500
MAX_EXPORTED_ENERGY_FRAMES = 700


def analyze_audio(audio_path: Path) -> AudioAnalysis:
    """Load mono audio and extract rhythmic and energy features.

    Returns an AudioAnalysis with both basic and enhanced features.
    Enhanced features include spectral flux, multi-band onsets,
    local BPM estimates, and tempo stability (requires raw samples).
    """

    audio_file = ensure_existing_file(audio_path, "Audio file")
    samples, sample_rate = _load_audio(audio_file)

    duration_ms = round_ms(len(samples) / sample_rate)
    if duration_ms < MIN_AUDIO_DURATION_MS:
        raise MapGeneratorError(
            f"Audio is too short for automatic mapping: {audio_file} is {duration_ms} ms long."
        )

    onset_envelope = librosa.onset.onset_strength(
        y=samples,
        sr=sample_rate,
        hop_length=HOP_LENGTH,
        aggregate=np.median,
    )
    rms = librosa.feature.rms(
        y=samples,
        frame_length=FRAME_LENGTH,
        hop_length=HOP_LENGTH,
        center=True,
    )[0]

    normalized_onset = _normalize(onset_envelope)
    normalized_rms = _normalize(rms)

    tempo, beat_frames = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=HOP_LENGTH,
        units="frames",
        trim=False,
        start_bpm=120.0,
        tightness=90,
    )
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_envelope,
        sr=sample_rate,
        hop_length=HOP_LENGTH,
        units="frames",
        backtrack=False,
        pre_max=3,
        post_max=3,
        pre_avg=3,
        post_avg=3,
        delta=0.03,
        wait=0,
    )

    beats = _collapse_timed_strengths(
        _build_timed_strengths(beat_frames, normalized_onset, sample_rate),
    )
    onsets = _collapse_timed_strengths(
        _build_timed_strengths(onset_frames, normalized_onset, sample_rate),
    )

    if not beats and not onsets:
        raise MapGeneratorError("Analysis returned no usable beats or onsets.")

    energy_frames = _compress_energy_frames(
        _build_energy_frames(normalized_rms, sample_rate),
    )
    quiet_regions = _detect_regions(energy_frames, threshold=0.18, mode="quiet")
    high_energy_regions = _detect_regions(energy_frames, threshold=0.68, mode="high")
    kiai_sections = _detect_kiai_sections(energy_frames, beats, duration_ms)
    offset_ms = _estimate_offset_ms(beats, onsets, energy_frames)

    # Enhanced features: compute spectral flux, multi-band onsets, local BPM
    enhanced = _compute_enhanced_features(
        samples=samples,
        sample_rate=sample_rate,
        duration_ms=duration_ms,
        beats=beats,
        onsets=onsets,
    )

    return AudioAnalysis(
        audio_filename=audio_file.name,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        bpm=float(np.atleast_1d(tempo)[0]) if np.size(tempo) else 0.0,
        offset_ms=offset_ms,
        beats=beats,
        onsets=onsets,
        energy_frames=energy_frames,
        quiet_regions=quiet_regions,
        high_energy_regions=high_energy_regions,
        analysis_version=2,
        enhanced=enhanced,
        kiai_sections=kiai_sections,
    )


def _compute_enhanced_features(
    samples: np.ndarray,
    sample_rate: int,
    duration_ms: int,
    beats: list[TimedStrength],
    onsets: list[TimedStrength],
) -> dict[str, Any]:
    """Compute enhanced rhythm analysis features.

    These features supplement the base analysis for the rhythm intelligence engine.
    All operations are deterministic.
    """
    from .rhythm.multi_layer_analysis import (  # lazy import to avoid circular deps
        DEFAULT_MULTI_LAYER_CONFIG,
        extract_enhanced_features,
        compute_bpm_regions,
        detect_subdivisions,
    )
    from .models import AudioAnalysis as AnalysisPlaceholder

    # Build a temporary AudioAnalysis for the sub-modules
    temp_analysis = AnalysisPlaceholder(
        audio_filename="",
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        bpm=0.0,
        offset_ms=0,
        beats=beats,
        onsets=onsets,
        energy_frames=[],
        quiet_regions=[],
        high_energy_regions=[],
        analysis_version=2,
    )

    enhanced = extract_enhanced_features(
        samples=samples,
        sample_rate=sample_rate,
        duration_ms=duration_ms,
        beats=beats,
        onsets=onsets,
        config=DEFAULT_MULTI_LAYER_CONFIG,
    )

    bpm_regions = compute_bpm_regions(
        beats=beats,
        onsets=onsets,
        duration_ms=duration_ms,
        config=DEFAULT_MULTI_LAYER_CONFIG,
    )

    subdivisions = detect_subdivisions(
        analysis=temp_analysis,
        beats=beats,
        onsets=onsets,
        duration_ms=duration_ms,
        config=DEFAULT_MULTI_LAYER_CONFIG,
    )

    return {
        "spectralFlux": enhanced.spectral_flux[:700],
        "spectralFluxTimesMs": enhanced.spectral_flux_times_ms[:700],
        "multiBandOnsetStrengths": {
            k: v[:700] for k, v in enhanced.multi_band_onset_strengths.items()
        },
        "localBpmEstimates": [
            {"timeMs": t, "bpm": b, "confidence": c}
            for t, b, c in enhanced.local_bpm_estimates
        ],
        "bpmRegions": [region.to_dict() for region in bpm_regions],
        "subdivisions": [sub.to_dict() for sub in subdivisions],
        "tempoStability": enhanced.tempo_stability,
    }


def _load_audio(audio_path: Path) -> tuple[np.ndarray, int]:
    try:
        samples, sample_rate = librosa.load(
            audio_path.as_posix(),
            sr=ANALYSIS_SAMPLE_RATE,
            mono=True,
        )
    except Exception as error:  # pragma: no cover - third-party decoder errors vary.
        ffmpeg_hint = ""
        if audio_path.suffix.lower() == ".mp3" and not is_ffmpeg_available():
            ffmpeg_hint = " FFmpeg is not available on PATH, so install FFmpeg if your local decoder cannot open MP3 files."

        raise MapGeneratorError(
            f"Audio could not be decoded from {audio_path}.{ffmpeg_hint} Original error: {error}"
        ) from error

    if samples.size == 0:
        raise MapGeneratorError(f"Audio file is empty or unreadable: {audio_path}")

    return samples.astype(np.float32, copy=False), sample_rate


def _normalize(values: np.ndarray) -> np.ndarray:
    if values.size == 0:
        return values

    maximum = float(np.max(values))
    if maximum <= 1e-8:
        return np.zeros_like(values, dtype=np.float32)

    return np.clip(values / maximum, 0.0, 1.0).astype(np.float32)


def _build_timed_strengths(
    frames: np.ndarray,
    normalized_strengths: np.ndarray,
    sample_rate: int,
) -> list[TimedStrength]:
    if frames.size == 0:
        return []

    frame_times = librosa.frames_to_time(frames, sr=sample_rate, hop_length=HOP_LENGTH)
    timed_values: list[TimedStrength] = []

    for frame_value, time_seconds in zip(frames, frame_times, strict=True):
        frame_index = int(frame_value)
        strength = float(normalized_strengths[frame_index]) if frame_index < len(normalized_strengths) else 0.0
        timed_values.append(
            TimedStrength(
                time_ms=round_ms(float(time_seconds)),
                strength=round(strength, 4),
            )
        )

    return timed_values


def _collapse_timed_strengths(items: list[TimedStrength]) -> list[TimedStrength]:
    strongest_by_time: dict[int, TimedStrength] = {}

    for item in items:
        existing = strongest_by_time.get(item.time_ms)
        if existing is None or item.strength > existing.strength:
            strongest_by_time[item.time_ms] = item

    return [strongest_by_time[key] for key in sorted(strongest_by_time)]


def _build_energy_frames(normalized_rms: np.ndarray, sample_rate: int) -> list[EnergyFrame]:
    frame_indices = np.arange(len(normalized_rms))
    frame_times = librosa.frames_to_time(frame_indices, sr=sample_rate, hop_length=HOP_LENGTH)

    return [
        EnergyFrame(
            time_ms=round_ms(float(time_seconds)),
            value=round(float(value), 4),
        )
        for time_seconds, value in zip(frame_times, normalized_rms, strict=True)
    ]


def _compress_energy_frames(frames: list[EnergyFrame]) -> list[EnergyFrame]:
    if len(frames) <= MAX_EXPORTED_ENERGY_FRAMES:
        return frames

    stride = int(np.ceil(len(frames) / MAX_EXPORTED_ENERGY_FRAMES))
    return frames[::stride]


def _detect_regions(
    frames: list[EnergyFrame],
    threshold: float,
    mode: str,
) -> list[EnergyRegion]:
    regions: list[EnergyRegion] = []
    current: list[EnergyFrame] = []

    def flush_region() -> None:
        nonlocal current
        if not current:
            return

        duration_ms = current[-1].time_ms - current[0].time_ms
        if duration_ms >= 360:
            average_value = float(np.mean([frame.value for frame in current]))
            regions.append(
                EnergyRegion(
                    start_ms=current[0].time_ms,
                    end_ms=current[-1].time_ms,
                    average_value=round(average_value, 4),
                )
            )
        current = []

    for frame in frames:
        matches = frame.value <= threshold if mode == "quiet" else frame.value >= threshold
        if matches:
            current.append(frame)
        else:
            flush_region()

    flush_region()
    return regions


def _detect_kiai_sections(
    energy_frames: list[EnergyFrame],
    beats: list[TimedStrength],
    duration_ms: int,
) -> list[KiaiSection]:
    """Detect kiai (chorus / high-energy) sections from energy frames.

    A kiai section is a sustained period where the average energy is
    significantly above the global median, with a minimum duration
    (~2 beats) and a confidence score derived from peak vs. median ratio.
    """
    if not energy_frames or len(energy_frames) < 10:
        return []

    values = [f.value for f in energy_frames]
    median_energy = float(np.median(values))
    if median_energy < 0.05:
        return []

    # Minimum energy threshold: 1.3x the median to qualify as "high"
    high_threshold = median_energy * 1.3
    # Minimum section duration: ~2 beats at typical BPM (~1600ms)
    min_section_ms = 1600
    # Merge gap: sections closer than this are merged
    merge_gap_ms = 800

    # Find contiguous runs above threshold
    runs: list[tuple[int, int, list[float]]] = []
    current_start: int | None = None
    current_values: list[float] = []

    for frame in energy_frames:
        if frame.value >= high_threshold:
            if current_start is None:
                current_start = frame.time_ms
                current_values = []
            current_values.append(frame.value)
        else:
            if current_start is not None:
                runs.append((current_start, frame.time_ms, current_values))
                current_start = None
                current_values = []

    if current_start is not None and current_values:
        runs.append((current_start, energy_frames[-1].time_ms, current_values))

    # Merge runs that are close together
    merged_runs: list[tuple[int, int, list[float]]] = []
    for run in runs:
        if merged_runs and run[0] - merged_runs[-1][1] <= merge_gap_ms:
            prev = merged_runs[-1]
            merged_runs[-1] = (
                prev[0],
                run[1],
                prev[2] + run[2],
            )
        else:
            merged_runs.append(run)

    # Filter by minimum duration and build KiaiSection objects
    sections: list[KiaiSection] = []
    for start_ms, end_ms, vals in merged_runs:
        duration = end_ms - start_ms
        if duration < min_section_ms:
            continue
        avg_energy = float(np.mean(vals))
        peak_energy = float(np.max(vals))
        # Confidence: ratio of peak to median, clamped to [0, 1]
        confidence = clamp((peak_energy / max(median_energy, 0.01) - 1.0) / 2.0, 0.0, 1.0)
        sections.append(KiaiSection(
            start_ms=start_ms,
            end_ms=end_ms,
            peak_energy=round(peak_energy, 4),
            average_energy=round(avg_energy, 4),
            confidence=round(confidence, 4),
        ))

    return sections


def _estimate_offset_ms(
    beats: list[TimedStrength],
    onsets: list[TimedStrength],
    energy_frames: list[EnergyFrame],
) -> int:
    def energy_at(time_ms: int) -> float:
        if not energy_frames:
            return 0.0
        closest = min(energy_frames, key=lambda frame: abs(frame.time_ms - time_ms))
        return closest.value

    candidates = [item for item in beats if item.strength >= 0.35]
    candidates.extend(item for item in onsets if item.strength >= 0.52)
    candidates.sort(key=lambda item: item.time_ms)

    for candidate in candidates:
        if energy_at(candidate.time_ms) >= 0.12:
            return candidate.time_ms

    if beats:
        return beats[0].time_ms

    if onsets:
        return onsets[0].time_ms

    return 0

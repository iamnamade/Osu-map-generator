# Phase 1 — Density, Interval & Fallback Diagnostic Report

**Scope:** `tools/map_generator/` — hit-object density, inter-object intervals, and low-confidence fallback fill.
**Role:** Senior osu! Rhythm & Gameplay Mechanics Analyst.
**Status:** Read-only audit. No production code was modified.
**Date:** 2026-09-27

---

## 1. Executive Summary

| Question | Verdict |
|---|---|
| Does **Hard** satisfy 2.5–3.8 obj/s? | ❌ **NO** — configured objective is 3.2 obj/s, but the only committed generation artifacts measure **1.64 obj/s**. |
| Does **Normal** satisfy 1.3–2.0 obj/s? | ✅ **YES** — configured objective 1.8 obj/s; measured **1.70 obj/s**. |
| Are min/max idle gaps bounded during active music? | ⚠️ **PARTIALLY** — max-gap logic exists but is energy-averaged and can be bypassed; observed **17 ms** minimum gaps violate every preset's `min_gap_ms`. |
| Does the engine create breaks during high-energy playback? | ⚠️ **No deliberate breaks**, but residual idle gaps can survive high-energy sections because suppression is average-energy gated and fill is deficit-capped. |
| Fallback fill preserves rhythmic flow? | ⚠️ **Grid-aligned and energy-scaled** (good), but **circles-only**, lowercase slider ratio, and bypasses onset/phrase anchoring. |

**Critical code findings (detailed in §5):**
1. `DifficultyPreset.max_gap_ms` (Phase 24) is **dead configuration** — declared for all tiers, never read at runtime.
2. `DifficultyPreset.min_slider_ratio` (Phase 24) is **dead configuration** — a duplicate of the live `slider_min_ratio`.
3. `_enforce_density_minimum()` collapses the minimum into the target via `max()`, so the "minimum" floor is never independently enforced.
4. `_select_by_density_and_gap()` updates `last_time` inconsistently across branches (`continue` skips the update).
5. Leftover debug `stderr` write in `slider_pipeline.py` shipped in the production path.

---

## 2. Density Metrics

### 2.1 Configured targets (single source of truth)
`tools/map_generator/config.py:68-72` defines the Phase 24 enforcement knobs:

```python
min_density_target: float = 0.0   # minimum objects/sec (0 = disabled)
target_density: float = 0.0       # target objects/sec (0 = disabled)
max_gap_ms: int = 0               # strict max gap (0 = disabled)
min_slider_ratio: float = 0.0     # (DEAD — see §5)
min_spinner_count: int = 0
```

Per-tier values (`config.py`):

| Preset | `min_density_target` | `target_density` | `min_gap_ms` | `target_gap_ms` | `max_gap_ms` (dead) | `max_empty_gap_ms` (live) |
|---|---|---|---|---|---|---|
| Easy | 0.8 (L128) | 1.2 (L129) | 420 | 880 | 3000 (L130) | 2400 (L100) |
| Normal | 1.3 (L186) | 1.8 (L187) | 240 | 580 | 2200 (L188) | 1800 (L158) |
| Hard | 2.2 (L244) | 3.2 (L245) | 140 | 340 | 1800 (L246) | 1400 (L216) |

A second, independent density system exists in the rhythm model: `rhythm/rhythm_density.py:8-22` (`DensityConfig.min_density=1.0`, `max_density=5.0`, `energy_ceiling=0.72`) computes energy-driven targets of **1.0–5.0 obj/s** (`compute_density_targets`, L41). These two systems are not reconciled — the rhythm model's density is used for selection confidence/scoring, while the preset's `target_density` drives object injection.

The difficulty analyzer also carries its own reference density (`difficulty/targets.py`): Easy **1.1**, Normal **1.5**, Hard **2.4** obj/s. Note Hard's analyzer target (2.4) sits **below** the requested spec floor (2.5).

### 2.2 Empirical metrics (committed artifacts)
Source: `.tmp-e2e-generation/maps/{easy,normal,hard}.json` + `.../reports/*-report.json`.
Test fixture: "Unit Test - Summary Song", **duration 16,431 ms (0.27385 min)**.

| Preset | Circles | Sliders | Spinners | Total | obj/s | Spec band | Result |
|---|---|---|---|---|---|---|---|
| Easy | 12 | 6 | 1 | 19 | **1.156** | (n/a) | — |
| Normal | 17 | 10 | 1 | 28 | **1.704** | 1.3–2.0 | ✅ PASS |
| Hard | 16 | 10 | 1 | 27 | **1.643** | 2.5–3.8 | ❌ FAIL (−0.86) |

**Per-minute breakdown (objects/min):**

| Preset | Circles/min | Sliders/min | Spinners/min | Total/min |
|---|---|---|---|---|
| Easy | 43.8 | 21.9 | 3.65 | 69.4 |
| Normal | 62.1 | 36.5 | 3.65 | 102.3 |
| Hard | 58.4 | 36.5 | 3.65 | 98.6 |

**Composition by type:**

| Preset | Circle % | Slider % | Spinner % |
|---|---|---|---|
| Easy | 63.2% | 31.6% | 5.3% |
| Normal | 60.7% | 35.7% | 3.6% |
| Hard | 59.3% | 37.0% | 3.7% |

**Interpretation:** Hard's object count is essentially identical to Normal's (27 vs 28). The generator is not differentiating Hard by density — it differentiates by spacing/speed/jump instead. The configured Hard objective (`target_density=3.2`) implies `int(3.2 × 16.431) = 52` objects; actual is 27, i.e. the density enforcement pass is failing to reach roughly half its quota.

> **Caveat:** these artifacts are the unit-test summary-song export and may predate the latest Phase 24 wiring. They are nonetheless the only committed generated output and are consistent with the observed enforcement shortfall in §3.3.

### 2.3 Density consistency signals
- Easy: `densityConsistency = 88.8`, `abruptDensitySpikes = 1`.
- Normal: `densityConsistency = 67.5`, `abruptDensitySpikes = 3`, `lowDensityHighEnergyWindows = 0`.
- Hard: `densityConsistency = 76.7`, `abruptDensitySpikes = 2`, `densityRatio = 0.677` (report self-classifies **"easier-than-target"**).

Hard's own validation report explicitly flags `DIFFICULTY_BEHAVIOR_TOO_EASY` — corroborating the density shortfall.

---

## 3. Break Times & Idle Intervals

### 3.1 Minimum gap (active music)
There are two independent floors.

**(a) Selection floor** — `preset.min_gap_ms` enforced in `rhythm/rhythm_pipeline.py:317-370` (`_select_by_density_and_gap`):
- Easy 420 ms, Normal 240 ms, Hard 140 ms.
- Then **phrase-scaled**: `_build_phrase_gap_lookup` (`rhythm_pipeline.py:415-449`) multiplies by `clamp(mean_density / phrase.expected_density, 0.6, 1.4)`.
  - Tightest case: Hard `140 × 0.6 = 84 ms`.
  - Loosest case: Easy `420 × 1.4 = 588 ms`.
- Floor is clamped at `max(60, …)` for min-gap and `max(90, …)` for target-gap.

**(b) Density-fill floor** — `beatmap_generator.py:707-711` re-checks `preset.min_gap_ms` against both neighbours before inserting a bridge object.

**(c) Observed violation:** reports show `minGapMs = 119` (Easy), `17` (Normal), `17` (Hard) with `RHYTHM_GAP_BELOW_MINIMUM` errors and a `SPINNER_OVERLAPS_PREVIOUS` **critical**. The 17 ms values pair a slider with a spinner start — i.e. spinner insertion post-dates the minimum-gap guard and is not re-validated against `min_gap_ms`. Spinner spacing uses only `preset.spinner_min_gap_ms` inside `spinners/spinner_pipeline.py:125`. Because the report was produced by a prior revision, this is flagged as a **likely latent bug**, not a confirmed current-code violation.

### 3.2 Maximum gap (active music)
The live path is `preset.max_empty_gap_ms` → `RhythmPipelineConfig.max_allowed_empty_gap_ms` (`beatmap_generator.py:133`), consumed at `rhythm_pipeline.py:360-377` via `rhythm_density.compute_max_allowed_gap` (`rhythm_density.py:193-226`):

```python
if avg_energy > energy_ceiling (0.72):  return max_gap * 0.35
elif avg_energy > midpoint (0.375):      return max_gap * 0.55
elif avg_energy > energy_floor (0.03):   return max_gap * 0.70
return max_gap
```

Effective ceilings (base = `max_empty_gap_ms`):

| Preset | Base | High energy (×0.35) | Mid energy (×0.55) | Low energy (×0.70) | True silence |
|---|---|---|---|---|---|
| Easy | 2400 | **840** | 1320 | 1680 | 2400 |
| Normal | 1800 | **630** | 990 | 1260 | 1800 |
| Hard | 1400 | **490** | 770 | 980 | 1400 |

Genuine silence is defined by `detect_silent_regions` (`rhythm_density.py:130`): energy ≤ `0.06` sustained for ≥ `2500 ms`. Inside those regions the full base gap is permitted (and density fill skips them).

Observed `maxGapMs` = **836** for all three tiers (identical fixture tail), comfortably inside every ceiling. `endingGapMs = 1245` for all tiers (end padding, expected).

### 3.3 Does the engine generate breaks during high-energy playback?
**No deliberate break objects exist** — there is no `break_period`/`breakPeriod` concept anywhere in `tools/map_generator/`. Breaks emerge only as **residual idle gaps**. The engine actively suppresses them in two places:

1. **Force-select** (`rhythm_pipeline.py:369-377`): if `gap > max_gap and not in_silent` and `confidence ≥ min_timing_confidence × 0.6`, the candidate is force-appended.
2. **Density fill** (`beatmap_generator.py:632+`): injects half-beat bridge circles into the largest gaps.

**Weaknesses that can still leak idle gaps into loud sections:**
- The ceiling test uses the **mean energy across the whole gap window**. A brief high-energy stab inside a mostly-quiet gap will not trip the ×0.35 tightening, permitting up to the full 1400 ms (Hard) inside a locally intense passage.
- Force-select requires `confidence ≥ min_timing_confidence × 0.6`. If the next candidate is too weak it is skipped and the gap persists — the loop does not search for a bridge point between candidates.
- `_enforce_density_minimum` fills only until `deficit` is exhausted and processes each gap **once**; if the budget runs out on early gaps, later high-energy gaps remain untouched.
- No explicit high-energy break guard exists independent of the averaged energy model.

**Answer:** the engine does not intentionally break high-energy playback, and its `lowDensityHighEnergyWindows` metric reads 0 across all tiers. But the suppression is heuristic and average-energy-gated, so isolated loud sections embedded in quieter gaps can retain long idles.

---

## 4. Fallback Fill Mechanics

### 4.1 `_enforce_density_minimum()` — `beatmap_generator.py:632-760`
Contract: inject bridging circles when the map is under its density target.

```python
if preset.min_density_target <= 0:            # L648 — gate
    return positioned
target_count = int(preset.min_density_target * duration_sec)          # L652
target_count = max(target_count,
                   int(preset.target_density * duration_sec) ...)      # L653
current_count = len(positioned.objects)
if current_count >= target_count:             # L656 — early out
    return positioned
deficit = target_count - current_count        # L659
```

Pipeline:
1. **Grid derivation** (L664-669): `bpm = analysis.bpm or 120.0`; `beat_interval = round(60000/bpm)`; `half_beat = beat_interval // 2`. Fallback BPM 120 → 500 ms beat / 250 ms half-beat.
2. **Gap discovery** (L672-681): scans consecutive sorted objects, `gap = next.time − previous.end_time` (slider-aware via `end_time`); keeps gaps `≥ 2 × half_beat` (≥ 1 full beat).
3. **Largest-first fill** (L685-747): sorts gaps descending; walks each gap in half-beat steps.
   - Skips times already occupied (`existing_times`).
   - Enforces `next.time − fill_time ≥ preset.min_gap_ms` and `fill_time − prev_time ≥ preset.min_gap_ms`.
   - **Position** (L719-736): linear interpolation between the two flanking objects plus a random perpendicular offset of `min_jump_distance × 0.5`, clamped to `[32,480]×[32,352]`; falls back to a random point when no neighbours.
   - **Strength** (L715): `0.25 + energy_at(fill_time) × 0.4` — energy-scaled, so fills still breathe with the music.
   - Tags `extra_fields = {"source": "density_fill", "energy": …}` (L734-737) for traceability.
4. **Reindex** (L750-773): rebuilds typed objects with clean sequential IDs and returns a new `PositionGenerationResult`.

**How it bridges low-confidence audio:** it ignores onset/beat confidence entirely and anchors to the **audio-derived BPM grid**, so injected notes are metrically consistent by construction. Intensity tracks local energy. Interpolation between real neighbours keeps cursor flow continuous. This is a sound strategy for preserving rhythmic flow through sections the onset detector could not resolve.

**Limitations:**
- `max()` at L653 means `target_density` dominates whenever it exceeds `min_density_target`; the "minimum" is never enforced on its own. Hard's true quota is 3.2 obj/s, not 2.2 obj/s — yet even that is not met empirically.
- Injects **circles only** — never sliders or spinners — which inflates circle share and depresses slider ratio. This is why a *second* post-density slider-ratio conversion pass exists (`beatmap_generator.py:~270-360`, `slider_pipeline.py:170-230`) and why the slider pipeline contains its own min-ratio second pass.
- Single-pass over each gap; no multi-pass or per-section redistribution once the deficit is spent.
- Bypasses phrase/onset anchoring — fills can land on grid points with no musical event. Report signal: Hard shows **8× `TIMING_NO_CONVINCING_ANCHOR`** and Normal **9 mistimed objects**.

### 4.2 `rhythm_pipeline._select_by_density_and_gap()` — `rhythm_pipeline.py:297-388`
The selection-stage fallback:
- **Subdivision filler** (`_add_subdivision_candidates`, L247-283): grid points become `source="subdivision"`, `phase="filler"` candidates, capped at 500 added, confidence floor 0.15, skipped inside silent regions.
- **Force-select on over-gap** (L369-377) as described in §3.3.
- **Low-confidence leniency** (L344-347): a low-confidence candidate is dropped unless it is a **beat** and `gap ≥ target_gap × 0.35`.
- **Phrase-aware gaps** (L415-449) tighten dense phrases and open recovery phrases within a bounded 0.6–1.4 scale.

### 4.3 Flow-preservation assessment
| Aspect | Rating | Notes |
|---|---|---|
| Metric alignment | ✅ Good | Half-beat grid + BPM fallback keeps fills metrically coherent. |
| Energy responsiveness | ✅ Good | Fill strength and max-gap both scale with `energy_at`. |
| Confidence bridging | ✅ Good | Confidence is intentionally bypassed to fill dead zones. |
| Anchor fidelity | ⚠️ Weak | Grid fills ignore onsets; produces `TIMING_NO_CONVINCING_ANCHOR`. |
| Object-type balance | ⚠️ Weak | Circles-only fill dilutes slider ratio; patched by extra passes. |
| Budget allocation | ⚠️ Weak | Largest-gap-first but single pass; no section-level rebalance. |
| Minimum-floor integrity | ❌ Broken | `max(min, target)` collapses the minimum objective. |

---

## 5. Code-Level Findings

| # | Severity | Location | Finding |
|---|---|---|---|
| F1 | 🔴 High | `config.py:70,130,188,246` | `DifficultyPreset.max_gap_ms` (Phase 24 "strict max gap") is **never read**. All max-gap enforcement actually flows through `max_empty_gap_ms`. The declared 3000/2200/1800 values are dead. |
| F2 | 🔴 High | `config.py:71,131,189,247` | `DifficultyPreset.min_slider_ratio` is **never read**. The live field is `slider_min_ratio` (Phase 11), used at `beatmap_generator.py:186`. Two same-purpose fields; the Phase 24 one is inert. |
| F3 | 🔴 High | `beatmap_generator.py:652-653` | `target_count = max(min_density_target, target_density) × duration` — the minimum is subsumed by the target, so `min_density_target` is only a gate flag, not a floor. Hard's advertised 2.2 floor is not enforced; the effective objective is 3.2. |
| F4 | 🟠 Medium | `rhythm_pipeline.py:344-388` | `last_time` is updated at the loop tail, but the `elif candidate.confidence >= …` branch `continue`s *before* that update (L383-385). Subsequent gap measurements therefore use a stale `last_time`. |
| F5 | 🟠 Medium | `rhythm_density.py:209-226` | Max-gap tightening keys on the **average** energy of the whole gap window, so isolated high-energy bursts inside a quieter gap do not trigger the ×0.35 ceiling. |
| F6 | 🟠 Medium | `beatmap_generator.py:685-747` | Fill is largest-gap-first but **single-pass** and circles-only; early deficits can starve later high-energy gaps, and injected circles depress the slider ratio. |
| F7 | 🟡 Low | `sliders/slider_pipeline.py:183-185` | Production `stderr.write("[FILL-CHECK] …")` debug line left in the fill path. Emits on every generation. |
| F8 | 🟡 Low | `rhythm_pipeline.py:369-377` | Force-select requires `confidence ≥ min_timing_confidence × 0.6`; if unmet the over-gap candidate is dropped with no alternative bridge search, allowing the idle gap to persist. |
| F9 | 🟡 Low | `config.py` vs `difficulty/targets.py` vs `rhythm_density.py` | Three unreconciled density references: preset 1.2/1.8/3.2 obj/s, analyzer 1.1/1.5/2.4 obj/s, rhythm model 1.0–5.0 obj/s. No single authority. |
| F10 | 🟡 Low | `spinners/spinner_pipeline.py:125` | Spinner spacing validates only `spinner_min_gap_ms` against the previous object *end*; the observed 17 ms start-to-start violations and `SPINNER_OVERLAPS_PREVIOUS` critical suggest `min_gap_ms` is not re-applied post-insertion. |

### Spec conformance against the stated requirements
- **Hard 2.5–3.8 obj/s:** objective 3.2 is inside the band, but (a) the floor is not enforced (F3), and (b) measured output is 1.64 obj/s. **Not satisfied.**
- **Normal 1.3–2.0 obj/s:** objective 1.8 and measured 1.70 are both inside the band. **Satisfied.**
- **Gap bounds:** min-floor is phrase-scaled down to 84 ms (Hard) and empirically undercut to 17 ms; max-ceiling is average-energy-gated and can be bypassed on isolated loud bursts. **Partially satisfied.**

---

## 6. Recommendations (no code changed)

1. **Enforce the minimum independently (F3):** separate the minimum floor from the target; validate `min_density_target` post-fill and treat `target_density` as a soft goal.
2. **Delete or wire dead config (F1, F2):** either drive max-gap from `preset.max_gap_ms` and slider floor from `min_slider_ratio`, or remove both fields to eliminate misleading knobs.
3. **Fix `last_time` (F4):** advance `last_time` on every append path in `_select_by_density_and_gap`.
4. **Harden high-energy gap detection (F5):** use peak/max energy (or a high percentile) in the gap window, not the mean, before deciding the ceiling multiplier.
5. **Multi-pass, type-aware fill (F6):** revisit gaps after the first injection pass and allow slider fills to protect the slider ratio.
6. **Reconcile density authorities (F9):** pick one canonical density target per tier and derive the others.
7. **Remove the debug line (F7)** before shipping.
8. **Re-validate spinner spacing against `min_gap_ms` (F10)** after spinner insertion.

---

## 7. Appendix — Key Code References

| Concern | File:Line |
|---|---|
| Preset density knobs (dataclass) | `config.py:68-72` |
| Easy / Normal / Hard enforcement values | `config.py:128-132`, `:186-190`, `:244-248` |
| Live max-gap wiring | `beatmap_generator.py:133` |
| Rhythm default max gap | `rhythm/rhythm_pipeline.py:33` |
| Selection gap logic | `rhythm/rhythm_pipeline.py:297-388` |
| Phrase gap scaling | `rhythm/rhythm_pipeline.py:415-449` |
| Subdivision filler | `rhythm/rhythm_pipeline.py:247-283` |
| Energy→density targets | `rhythm/rhythm_density.py:41-125` |
| Silent-region detection | `rhythm/rhythm_density.py:130-167` |
| Max-allowed-gap scaling | `rhythm/rhythm_density.py:193-226` |
| Density enforcement | `beatmap_generator.py:632-760` |
| Post-density slider ratio pass | `beatmap_generator.py:262-360` |
| Slider min-ratio fill + debug | `sliders/slider_pipeline.py:103`, `:170-230` |
| Spinner gap validation | `spinners/spinner_pipeline.py:119-125` |
| Analyzer density targets | `difficulty/targets.py` |
| Density validation windows | `validation/density_validator.py:8-53` |

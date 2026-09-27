# Section-Aware Mapping

## Purpose

Phase 7 adds an original deterministic section-aware pipeline on top of the existing Phase 5 tournament candidates and Phase 6 editor.

The pipeline now does:

1. Analyze audio features that already exist in the project.
2. Detect meaningful section boundaries.
3. Label each section heuristically.
4. Score every candidate map per section.
5. Select a full hybrid source sequence with dynamic programming.
6. Check transitions between adjacent selected sections.
7. Apply conservative deterministic transition fixes when they improve safety.
8. Assemble one browser-compatible hybrid map.
9. Validate the hybrid with the authoritative Python validator.
10. Export reports for gameplay, review, and editor visualization.

## Important limits

- Section labels are estimates, not ground truth.
- The system does not understand lyrics.
- Hybrid scores are internal project metrics, not official osu! values.
- Hybrid maps still require human review.
- The editor remains circle-only.
- `.osu` export is not part of Phase 7.
- Machine learning is not used in this phase.

## Core signals

The detector reuses the Phase 2 analysis JSON where possible. The current implementation is built from:

- RMS energy frames
- Energy slope and energy contrast
- Beat density
- Onset density
- Onset strength
- Quiet-region overlap
- High-energy-region overlap
- Event-emphasis changes

No pretrained models, remote APIs, or external beatmap generators are used.

## Boundary detection

Boundaries are proposed from existing beat and onset anchors, then scored from feature changes across a configurable window. The detector prefers larger energy and density shifts, quiet-to-loud changes, and high-energy contrast changes.

Current default rules:

- Minimum section duration: `6000 ms`
- Boundary window: `2400 ms`
- Snap tolerance: `260 ms`
- Candidate boundaries must remain strictly increasing
- Output sections always cover the full analyzed audio duration

The detector does not split the song into equal chunks. It only keeps anchors that cross the configured confidence threshold.

## Boundary snapping

Each boundary keeps:

- `rawTimeMs`
- `finalTimeMs`
- `confidence`
- `reason`
- `supportingFeatureChanges`
- `snapped`
- `snappedTo`
- `snapDistanceMs`

Snapping is conservative. A boundary only moves to a nearby beat or onset when the anchor is close enough to preserve the original musical change point.

## Heuristic labels

Current supported labels:

- `intro-like`
- `verse-like`
- `build-up`
- `chorus-like`
- `drop-like`
- `break-like`
- `bridge-like`
- `outro-like`
- `instrumental`
- `quiet`
- `unknown`

Labels combine position-in-song context, energy class, density, and trend. They are heuristic tags for scoring, not claims of deep structural understanding.

## Section analysis output

Primary output:

- `public/sections/test-song-sections.json`

The artifact is deterministic and intentionally avoids current timestamps. It stores:

- section spans
- boundary metadata
- per-section energy and density summaries
- label confidence
- repetition grouping
- pipeline configuration snapshot

## Candidate section evaluation

The evaluator reads existing Phase 5 candidate folders and does not regenerate candidates when valid artifacts already exist.

Current behavior:

- Reads `improved-map.json`
- Reads `candidate-summary.json`
- Reuses existing section reports when the input signature matches
- Regenerates missing or stale section reports

Per-candidate outputs:

- `public/section-reports/test-song/easy/candidate-001-sections.json`
- `public/section-reports/test-song/normal/candidate-001-sections.json`
- `public/section-reports/test-song/hard/candidate-001-sections.json`

Each section report stores:

- local scores
- local metrics
- issues
- entry state
- exit state

## Section scoring

Every candidate section currently receives:

- `structural`
- `timing`
- `rhythm`
- `movement`
- `readability`
- `spatialBalance`
- `repetition`
- `densityConsistency`
- `difficultyConsistency`
- `transitionReadiness`
- `overall`

The current scorer adapts density expectations by label:

- quiet and intro-like sections prefer lower density and smoother movement
- build-up sections reward controlled escalation
- chorus-like and drop-like sections allow stronger movement and emphasis
- break-like sections reward recovery and contrast

## Global hybrid selection

The selector does not greedily choose the highest isolated section score. It uses a deterministic dynamic-programming pass over section candidates.

Each path combines:

- section-local quality
- timing, movement, and rhythm rewards
- candidate quality and stability bias
- transition compatibility
- style consistency
- candidate-switch penalty

This keeps the final hybrid from turning into a patchwork of disconnected local winners.

## Candidate-switch penalty

Adjacent section source changes currently receive a small configurable penalty:

- default switch penalty: `2.8`

Switching is still allowed when the local and transition gains are worth it.

## Transition analysis

Each adjacent section join currently measures:

- cross-boundary time gap
- cross-boundary distance
- required cursor speed
- direction-angle change
- local density before and after the boundary
- pattern continuity
- stacking risk
- approach overlap risk
- whether the same source candidate continues

Current transition classes:

- `excellent`
- `safe`
- `borderline`
- `unsafe`
- `critical`

## Transition optimization

The optimizer is conservative and deterministic. It works in this order:

1. Safe position adjustment
2. Small timing adjustment toward a nearby anchor
3. Alternate section-source swap
4. Boundary object removal
5. One anchored transition-object insertion

Every accepted action must improve the transition score. Failed attempts are recorded as reverted corrections in the transition log.

## Hybrid assembly

Current hybrid outputs:

- `public/maps/hybrid/test-song-easy.json`
- `public/maps/hybrid/test-song-normal.json`
- `public/maps/hybrid/test-song-hard.json`

Authoritative validation outputs:

- `public/reports/hybrid/test-song-easy-report.json`
- `public/reports/hybrid/test-song-normal-report.json`
- `public/reports/hybrid/test-song-hard-report.json`

Assembly reports:

- `public/hybrids/test-song-easy-assembly.json`
- `public/hybrids/test-song-normal-assembly.json`
- `public/hybrids/test-song-hard-assembly.json`

Transition logs:

- `public/hybrids/test-song-easy-transitions.json`
- `public/hybrids/test-song-normal-transitions.json`
- `public/hybrids/test-song-hard-transitions.json`

The final map keeps:

- sequential IDs
- strictly increasing times
- legal coordinates
- optional hybrid metadata that gameplay ignores

Original candidate maps are never mutated in place.

## Hybrid scoring

Current hybrid score formula:

- Section quality: `50%`
- Transition quality: `25%`
- Style consistency: `10%`
- Final Python quality: `15%`

The score is clamped to `0-100`.

## Promotion rules

The hybrid is marked promoted only when it passes the internal rule set:

- valid
- playable
- no structural error blockers
- hybrid score at or above `80.0`
- Python quality not meaningfully below the champion by more than `2.5`

Even when promotion fails, the hybrid artifacts are still exported for inspection.

## Resume behavior

Current Phase 7 resume behavior:

- section analysis is reused when the input signature matches
- candidate section reports are reused when the input signature matches
- missing or stale artifacts are regenerated
- hybrid assembly is recomputed from current inputs

Partial outputs are not treated as complete.

## Determinism

The pipeline avoids current timestamps in deterministic artifacts and uses input signatures to decide reuse. Identical inputs should produce identical:

- boundaries
- section labels
- section reports
- section-source selections
- transition logs
- hybrid maps
- hybrid assembly reports

## CLI commands

Analyze sections:

```bash
python -m tools.map_generator.cli analyze-sections \
  --audio public/audio/test-song.mp3 \
  --analysis public/analysis/test-song-analysis.json \
  --output public/sections/test-song-sections.json
```

Evaluate candidate sections:

```bash
python -m tools.map_generator.cli evaluate-sections \
  --sections public/sections/test-song-sections.json \
  --candidates-root public/candidates/test-song/normal \
  --difficulty normal \
  --output-dir public/section-reports/test-song/normal
```

Assemble a hybrid:

```bash
python -m tools.map_generator.cli assemble-hybrid \
  --sections public/sections/test-song-sections.json \
  --candidates-root public/candidates/test-song/normal \
  --difficulty normal \
  --output-map public/maps/hybrid/test-song-normal.json \
  --output-report public/reports/hybrid/test-song-normal-report.json \
  --assembly-report public/hybrids/test-song-normal-assembly.json \
  --transition-log public/hybrids/test-song-normal-transitions.json
```

Run all difficulties:

```bash
python -m tools.map_generator.cli hybrid-all \
  --audio public/audio/test-song.mp3 \
  --analysis public/analysis/test-song-analysis.json \
  --seed 42
```

Compare hybrids:

```bash
python -m tools.map_generator.cli compare-hybrids \
  --hybrids-dir public/hybrids
```

## Package scripts

Windows-friendly scripts added in `package.json`:

- `npm run sections:analyze`
- `npm run sections:evaluate:easy`
- `npm run sections:evaluate:normal`
- `npm run sections:evaluate:hard`
- `npm run hybrid:easy`
- `npm run hybrid:normal`
- `npm run hybrid:hard`
- `npm run hybrid:all`
- `npm run compare:hybrids`

These route through:

- `scripts/run-section-pipeline.mjs`

## Frontend game integration

The shared map catalog now exposes:

- `Hybrid Easy`
- `Hybrid Normal`
- `Hybrid Hard`

The existing Phaser gameplay scene is reused without duplication. Missing hybrid maps show a readable Phase 7-specific message.

## Editor integration

The editor now loads section and hybrid artifacts when available and adds:

- a dedicated section track in the timeline
- section selection by clicking the section track
- seek, play, loop, zoom, and lock controls for the selected section
- a Hybrid panel with source sequence, transition status, and promotion summary

Locking in the editor is local metadata only. The browser does not trigger Python regeneration.

## Known limitations

- Current section detection only uses signals already present in the project analysis output.
- Short songs may naturally produce only a small number of sections.
- Transition optimization is intentionally conservative.
- The browser editor visualizes hybrid data but does not rebuild hybrids.
- Candidate section evaluation is heuristic and should still be reviewed by a human.

## Why machine learning is not used yet

Phase 7 is deliberately heuristic and deterministic. That keeps the pipeline explainable, debuggable, reproducible, and fully local while the project establishes strong non-ML baselines for section detection, transition safety, and hybrid assembly.

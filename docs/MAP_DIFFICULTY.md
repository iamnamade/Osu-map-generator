# Map Difficulty Intelligence & Star Rating

## Purpose

Phase 13 adds a complete, deterministic Difficulty Intelligence Engine to the
generator pipeline. The generator now understands *why* a map is easy or
difficult by estimating player skill requirements across multiple dimensions.

The goal is **not** to reproduce osu!'s official star rating. This is our own
transparent, deterministic difficulty evaluation system that can later be
calibrated against real maps.

## Scope

This phase is analysis-first. It:

- computes raw difficulty metrics for any map
- produces a difficulty profile, heatmap, and timeline curve
- scores patterns, sections, and individual objects
- estimates reading, rhythm, aim, and stamina demand
- computes a modular custom star-rating breakdown
- estimates gameplay analytics (miss probability, combo stability, stress)
- rebalances a map toward a difficulty target (optional pass)
- verifies difficulty consistency and target tolerance
- renders all of it live in the editor

It does **not** change the workspace format, the external generation workflow,
the export/import format, or the editor's existing UI shell.

## Architecture

```
tools/map_generator/difficulty/
  __init__.py       public API (analyze_map, rebalance_map, helpers)
  models.py         dataclasses: DifficultyReport, StarRating, sections, ...
  common.py         shared helpers (clamp, mean, norm, bucket helpers)
  loader.py         parse a project beatmap JSON into difficulty structures
  metrics.py        raw metric computation (density, jumps, velocity, angles)
  reading.py        reading complexity (spacing, stacking, clutter, ambiguity)
  rhythm.py         rhythm complexity (syncopation, subdivisions, switches)
  aim.py            aim demand (distance, speed, precision, angles, flow)
  stamina.py        stamina demand (continuous activity, rest, slider load)
  patterns.py       pattern classification + scoring
  curves.py         per-moment difficulty timeline + section scoring
  stars.py          modular star-rating model (overall + 6 sub-stars)
  targets.py        difficulty presets (easy ... expert, custom)
  gameplay.py       simulated-play analytics
  diagnostics.py    histogram, object contribution, hardest objects
  rebalancer.py     adaptive rebalancing toward a target
  analyzer.py       orchestrator that ties everything into a report
  report_writer.py  JSON report output
tools/map_generator/validation/
  difficulty_intelligence_validator.py   validator checks
src/shared/
  difficultyReport.ts   shared TS report types + strict parser
  difficultyEngine.ts   live TS difficulty engine (mirrors Python logic)
src/game/
  DifficultyReportLoader.ts   loads + validates saved reports
src/editor/panels/
  DifficultyPanel.ts         live editor panel
```

## Pipeline Integration

After map generation, the local API pipeline runner runs a `difficulty` stage
that produces `difficulty/difficulty.json` inside each workspace. The artifact
service registers the report as a downloadable artifact, and the workspace
manifest records it.

CLI:

```bash
python -m tools.map_generator.cli difficulty \
  --map public/maps/generated/test-song-easy.json \
  --analysis public/analysis/test-song-analysis.json \
  --difficulty easy \
  --sections public/sections/test-song-sections.json \
  --output public/difficulty/test-song-easy-difficulty.json
```

A Node wrapper is available at `scripts/run-map-difficulty.mjs` and in
`package.json` as `map:difficulty`.

## Metrics

The engine computes (all deterministic):

- object count, objects per second
- circle / slider / spinner density
- jump distance (average, max, standard deviation)
- cursor velocity and acceleration
- angle complexity, direction changes
- stream length, burst length
- slider complexity (velocity, repeats, length)
- reaction time (average, minimum)
- recovery window count
- pattern variation, stamina demand, rhythm complexity

## Difficulty Dimensions

Each dimension is normalized to a `0..1` score and contributes to stars:

| Dimension | What it measures |
| --- | --- |
| Reading | spacing complexity, stacking, overlap, visual clutter, approach timing, direction ambiguity, pattern recognition |
| Rhythm | syncopation ratio, subdivision variety, rhythm switches, timing consistency, tempo changes, off-beat notes, triplets, bursts |
| Aim | distance demand, speed demand, precision, sharp turns, flow, micro-adjustments, large jumps |
| Stamina | continuous activity, high-density duration, stream duration, rest frequency, slider workload |
| Technical | angle complexity, direction changes, slider complexity, pattern scores |

## Patterns

Sliding windows are classified and scored independently:

- streams, bursts
- cross-screen jumps, wide jumps
- triangles, rectangles
- slider chains
- technical patterns (sharp turns)
- dense clusters

## Star Rating

`stars.py` / `difficultyEngine.ts` compute:

- overall stars
- aim / speed / reading / rhythm / stamina / technical stars

Star models are exponent-scaled per axis and combined with fixed weights. The
full breakdown (components + weights) is included in the report for later
calibration.

## Difficulty Targets

Presets in `targets.py`:

| Name | Star range |
| --- | --- |
| Easy | 1.0 - 2.6 |
| Normal | 2.2 - 3.9 |
| Hard | 3.6 - 5.4 |
| Insane | 5.2 - 6.8 |
| Expert | 6.6 - 8.4 |
| Custom | 0.8 - 8.0 |

Each target also encodes density, jump, speed, and reading expectations. In the
editor, the target comes from the loaded map's `difficulty` field.

## Adaptive Rebalancing

`rebalancer.py` adjusts a map toward its target:

- **Over target**: reduce jumps, reduce density, replace difficult sliders,
  insert recovery gaps
- **Under target**: increase density, increase movement, increase rhythm
  variation, increase pattern complexity

Rebalancing is an explicit optional pass; the analyzer itself never mutates
maps.

## Report

Each report (`DifficultyReport`) contains:

- overall stars, star breakdown
- raw metrics summary
- reading / rhythm / aim / stamina summaries
- pattern analysis
- section analysis + heatmap + timeline curve
- object difficulty + contribution
- gameplay analytics
- recommended player level
- difficulty consistency, peak / average difficulty
- confidence score
- verification issues
- diagnostics (histogram, hardest objects, star calculation summary)
- deterministic signature

## Validation Checks

`difficulty_intelligence_validator.py` verifies:

- difficulty consistency (no wild section swings)
- target tolerance (overall stars within target range)
- section balance
- no impossible spikes
- reasonable transitions between sections

## Editor Integration

The editor's new **Difficulty** tab runs the live TS engine on every edit:

- overall stars + axis bars
- live target match badge
- difficulty curve (SVG) + density overlay
- section difficulty list
- pattern scores
- gameplay estimates
- hardest objects
- saved Python report baseline + live edit delta

The panel recomputes whenever `changedRevision` changes, so recalculation is
live but cheap.

## Determinism

Given identical audio, seed, settings, and difficulty target, the same
difficulty evaluation is always produced. The report includes a deterministic
`signature` string derived from the input map and settings.

## Verification

- Python: `python -m tools.map_generator.tests.test_difficulty`
- Node wrapper: `npm run map:difficulty -- --help`

## Known Limitations

- This is **not** osu! official star rating; values differ from osu! SR.
- Star weights are initial heuristics, not calibrated against real maps.
- Reading metrics do not yet use per-timing-point AR scaling.
- Stamina modeling uses timing-gap proxies rather than per-tap cost models.
- The live editor engine mirrors the Python logic but is a separate
  implementation; signature equality between them is not guaranteed yet.
- Rebalancing is conservative and only runs as an explicit pass.

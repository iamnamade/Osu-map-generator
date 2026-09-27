# Phase 5 Map Tournaments

## Purpose

Phase 5 adds deterministic multi-candidate generation and tournament selection to the browser rhythm-game project.

Instead of trusting one generated map per difficulty, the pipeline now:

1. generates multiple controlled candidates
2. validates each original candidate
3. post-processes each candidate
4. validates each improved candidate
5. measures diversity and stability
6. ranks eligible candidates
7. exports one champion map

Tournament scores are internal project metrics.

They are not official osu! ratings.

Champion selection improves reliability, but it does not guarantee a perfect map.

Human review is still valuable.

## Why Multiple Candidates Help

The Phase 2 generator was already deterministic, but it still depended heavily on one placement seed.

Phase 5 reduces that single-seed dependence by comparing several full-map candidates that all target the same difficulty and audio analysis.

This phase still selects one complete map as the winner.

It does not merge sections from different maps yet.

## Candidate Seed Derivation

Each candidate receives a deterministic seed derived from:

- root seed
- difficulty
- candidate index
- candidate variation signature

The implementation uses stable `BLAKE2` hashing.

It never relies on Python's unstable hash behavior.

The same:

- audio
- analysis
- difficulty
- root seed
- candidate count
- timing-variation mode
- code version

produces identical candidate seeds and identical outputs.

## Controlled Variation

Candidates are not created by changing only the placement seed.

Phase 5 applies small deterministic variation to safe generator parameters such as:

- preferred jump distance
- pattern variation
- edge penalty
- recent-position penalty
- repetition penalty
- center-recovery weight
- energy influence
- strength influence
- arc bias
- alternation bias
- continuation bias
- triangle bias
- direction jitter

When `--timing-variation` is enabled, candidates may also vary:

- onset strength threshold
- beat strength threshold
- strong-beat threshold
- target gap preference
- merge tolerance
- weak-event confidence bias

Timing variation is disabled by default.

When disabled, all candidates reuse the same selected event times so placement quality can be compared fairly.

## Candidate Directory Structure

Outputs are grouped by song slug, difficulty, and candidate index.

Example:

```text
public/
  candidates/
    test-song/
      normal/
        candidate-001/
          original-map.json
          original-report.json
          improved-map.json
          improved-report.json
          corrections.json
          candidate-summary.json
```

This keeps candidate artifacts inspectable without dumping every file into one folder.

## Pipeline

Each candidate runs through the same deterministic stages:

1. generate original candidate
2. validate original candidate
3. post-process candidate
4. validate improved candidate
5. compute candidate metrics
6. compute diversity metrics
7. compute stability metrics
8. compute tournament score
9. rank eligible candidates
10. copy the champion map and report

## Eligibility Rules

A candidate is rejected from champion selection when:

- required output files are incomplete
- the improved report is invalid
- the improved report is not playable
- any critical issue remains
- structural errors remain
- maximum cursor speed exceeds the hard safety limit
- object count is zero
- scores are non-finite
- deterministic metadata checks fail

Rejected candidates are never silently discarded.

Their rejection reasons are stored in the candidate summary and the tournament report.

If every candidate is rejected, the command fails with a readable error and preserves the generated candidate directories for inspection.

## Tournament Scoring Formula

Weights are centralized in `tools/map_generator/candidates/candidate_config.py`.

Current weights:

- improved overall quality: `60%`
- safety and unresolved issues: `15%`
- stability: `10%`
- difficulty consistency: `5%`
- post-processing efficiency: `5%`
- diversity contribution: `5%`

The tournament score is always clamped to `0..100`.

### Safety Component

The safety component blends strong validator categories and then applies explicit penalties for:

- critical issues
- errors
- warnings
- movement speed violations
- mistimed objects
- near-limit runs

### Post-Processing Efficiency

The efficiency component prefers candidates that finish strong without requiring heavy corrective surgery.

It penalizes:

- destructive corrections
- reverted corrections
- large timing adjustments
- large coordinate shifts
- excessive accepted actions

It gives a small reward to candidates that achieve meaningful improvement safely.

## Stability Scoring

The stability score estimates how fragile the final candidate is.

Current inputs include:

- distance from the difficulty cursor-speed limit
- distance from the minimum timing-gap limit
- near-threshold warnings
- reverted corrections
- accepted correction magnitude
- original-to-improved score swing
- severe local sections
- remaining errors or critical issues

Interpretation:

- `90-100`: very stable
- `80-89`: stable
- `70-79`: mostly stable
- `60-69`: borderline
- `below 60`: fragile

This is a deterministic heuristic, not a simulation of hundreds of threshold variants.

## Diversity Scoring

Diversity is calculated pairwise across improved candidates.

The current comparison uses:

- average coordinate difference
- jump-distance histogram difference
- spatial-region usage difference
- angle-distribution difference
- timing difference when timing variation is enabled

Candidates above the near-duplicate similarity threshold are grouped as near duplicates.

Near duplicates are still kept for inspection, but they receive a small similarity penalty in tournament scoring.

The diversity summary records:

- candidate count
- eligible count
- unique candidate count
- near-duplicate groups
- average pairwise diversity
- minimum pairwise diversity
- maximum pairwise diversity
- most unique candidate
- most duplicated candidate

## Ranking And Tie-Breaking

Only eligible candidates are ranked.

Tie-breaking is deterministic and uses this order:

1. higher tournament score
2. higher improved overall quality
3. higher stability score
4. fewer errors
5. fewer warnings
6. fewer destructive corrections
7. higher difficulty-consistency score
8. lower candidate index

There is no random tie-break.

## Champion Export

The winning improved candidate is copied to stable public output paths:

- `public/maps/champions/test-song-easy.json`
- `public/maps/champions/test-song-normal.json`
- `public/maps/champions/test-song-hard.json`

And:

- `public/reports/champions/test-song-easy-report.json`
- `public/reports/champions/test-song-normal-report.json`
- `public/reports/champions/test-song-hard-report.json`

And:

- `public/tournaments/test-song-easy-tournament.json`
- `public/tournaments/test-song-normal-tournament.json`
- `public/tournaments/test-song-hard-tournament.json`

The champion map is copied directly from the winning improved candidate.

It is not modified during champion export.

## Resume Behavior

Default behavior is resume-safe:

- a fully complete candidate directory is reused
- an incomplete candidate directory is regenerated
- final ranking is recomputed after every run
- reused and regenerated counts are runtime-only console details and are not stored in deterministic JSON artifacts

Phase 5 treats a candidate directory as complete only when all required artifacts and the summary file exist.

## Force Regeneration

Use `--force` to regenerate every candidate even when complete directories already exist.

This is useful after tuning heuristics or when you want to explicitly refresh all candidate artifacts.

## CLI Commands

Single difficulty:

```powershell
python -m tools.map_generator.cli tournament `
  --audio public/audio/test-song.mp3 `
  --analysis public/analysis/test-song-analysis.json `
  --title "Test Song" `
  --artist "Unknown Artist" `
  --difficulty normal `
  --count 10 `
  --seed 42 `
  --output-root public/candidates/test-song/normal `
  --champion-map public/maps/champions/test-song-normal.json `
  --champion-report public/reports/champions/test-song-normal-report.json `
  --tournament-report public/tournaments/test-song-normal-tournament.json
```

All difficulties:

```powershell
python -m tools.map_generator.cli tournament-all `
  --audio public/audio/test-song.mp3 `
  --analysis public/analysis/test-song-analysis.json `
  --title "Test Song" `
  --artist "Unknown Artist" `
  --seed 42
```

Compare tournament reports:

```powershell
python -m tools.map_generator.cli compare-tournaments `
  --tournaments-dir public/tournaments
```

Inspect one candidate:

```powershell
python -m tools.map_generator.cli inspect-candidate `
  --summary public/candidates/test-song/normal/candidate-004/candidate-summary.json `
  --verbose
```

## Package Scripts

Windows-friendly shortcuts:

- `npm run tournament:easy`
- `npm run tournament:normal`
- `npm run tournament:hard`
- `npm run tournament:all`
- `npm run compare:tournaments`

These use `scripts/run-map-tournament.mjs`, which follows the same Python-discovery conventions as the existing generator and post-processor helpers.

## Tournament Report Format

Each tournament report stores:

- song metadata
- root seed and candidate count
- timing-variation mode
- generated, eligible, rejected, and unique counts
- champion summary
- eligible ranking
- rejected candidates
- diversity summary
- centralized score weights

The report is written as deterministic UTF-8 JSON.

It does not store wall-clock timestamps.

## Frontend Integration

The browser map selector now includes:

- `Champion Easy`
- `Champion Normal`
- `Champion Hard`

Champion selections use the same Phaser gameplay scene as every other map source.

When a champion map is selected and its tournament report exists, the UI shows:

- champion candidate number
- tournament score
- quality score
- stability score
- generated candidate count
- eligible count
- rejected count
- near-duplicate count
- top three candidates

If the champion map exists but the tournament report does not, gameplay still works and the UI shows a readable missing-report message.

## Determinism Guarantees

Phase 5 is designed so identical inputs produce identical:

- candidate maps
- validation reports
- correction logs
- candidate summaries
- ranking order
- champion map
- tournament report

The implementation uses stable hashing and avoids unstable timestamp metadata in deterministic artifacts.

## Known Limitations

Phase 5 currently:

- selects one complete candidate map instead of combining sections
- works only with circles
- still uses rule-based heuristics
- does not export `.osu`
- does not compute official star ratings
- does not include manual map editing
- does not learn style from datasets or machine learning models
- does not publish maps automatically

## Why Hybrid Section Merging Is Not Included Yet

Section-level merging is intentionally deferred.

Phase 5 focuses on picking the strongest single complete candidate because that gives us:

- a simpler determinism story
- safer validation and post-processing
- easier debugging
- clearer champion provenance

Hybrid section assembly can be explored in a later phase after the candidate tournament pipeline is stable and well-understood.

# Phase 4 Map Post-Processing

## Purpose

Phase 4 adds a deterministic rule-based post-processor for our browser rhythm maps.

It takes:

- a generated beatmap JSON
- the existing audio analysis JSON
- the existing validation report JSON
- the selected difficulty preset

It then:

- creates a safe editable copy
- applies small targeted corrections
- revalidates every accepted candidate
- compares before and after quality
- keeps the stronger validated result
- writes a correction log JSON

This is not an official osu! approval or ranking system. It is an internal quality-improvement pass for our own browser map format.

## Original-Map Safety

The post-processor never overwrites the source generated map.

Safety rules:

1. The source map is only read.
2. All edits happen on a copied in-memory map.
3. The final selected result is written to a separate output path.
4. The correction log is always written separately.
5. The same seed produces the same correction decisions for the same inputs.

## Processing Stages

The pipeline uses these stages:

1. `structural_safety`
2. `timing_corrections`
3. `movement_corrections`
4. `stacking_corrections`
5. `density_corrections`
6. `repetition_corrections`
7. `difficulty_corrections`
8. `local_optimization`

Each candidate change is revalidated before it is accepted.

## Supported Correction Types

Phase 4 supports these correction action types:

- `move_object`
- `adjust_time`
- `remove_object`
- `insert_object`

Current behavior is intentionally conservative:

- movement changes are the default correction
- timing changes are limited by difficulty
- removals are rare
- insertions only happen on strong unused musical anchors

## Timing Rules

Timing corrections use nearby beats and onsets from the existing analysis file.

The default maximum timing adjustments are:

- Easy: `70ms`
- Normal: `55ms`
- Hard: `40ms`

Timing changes are rejected when they would:

- create duplicate timestamps
- break strict increasing order
- violate minimum object gaps
- fail to improve timing or related report quality

## Movement Rules

Movement corrections target issues such as:

- `MOVEMENT_SPEED_EXCEEDED`
- `MOVEMENT_LARGE_JUMP_LOW_ENERGY`
- `MOVEMENT_ISOLATED_JUMP_SPIKE`
- `MOVEMENT_EDGE_TO_EDGE_RUSH`

For one problematic object, the system:

1. keeps timing unchanged by default
2. generates deterministic candidate positions
3. scores them using local spacing, speed, direction, and edge pressure
4. validates the candidate map
5. keeps only candidates that measurably improve the result

## Density Rules

Density corrections use the validation windows plus the existing audio energy data.

Supported patterns:

- map too dense for low energy
- map too sparse for high energy
- unexplained density spikes
- overly empty active endings

Removal rules:

- avoid the first and last object
- avoid strong anchors
- prefer weak low-energy objects
- keep removals under the configured percentage limits

Insertion rules:

- only use strong unused beats or onsets
- require safe minimum gaps on both sides
- generate a safe playable position
- keep insertions under the configured percentage limits

## Repetition Rules

The repetition stage looks for accidental loops and motif overuse such as:

- repeated two-point loops
- repeated coordinate-pair reuse
- repeated short pattern sequences

It normally breaks the repetition by moving a single object in the repeated run.

## Difficulty Consistency Rules

The difficulty stage uses our own preset behavior model, not official star rating logic.

It mainly targets:

- `DIFFICULTY_BEHAVIOR_INCONSISTENT`
- `DIFFICULTY_BEHAVIOR_TOO_HARD`
- `DIFFICULTY_BEHAVIOR_TOO_EASY`

Typical fixes are:

- reducing one isolated jump spike
- smoothing one local movement burst
- adding or removing a clearly justified density event

## Acceptance And Rejection

A candidate is accepted when it:

- introduces no critical structural issue
- stays playable
- improves the targeted metric or meaningfully improves overall quality
- stays within configured modification limits

A candidate is rejected when it:

- introduces a critical issue
- becomes unplayable
- adds too many errors
- breaks timing safety
- exceeds modification limits
- fails to create a meaningful validated improvement

At the end, the system keeps the improved result only when the validated outcome is stronger overall, or when it removes severe problems without meaningful quality loss.

## Deterministic Seeds

Use the same seed with the same source map, report, analysis, and configuration to get the same result.

Different seeds may change movement candidate ordering, but they do not force timing changes when timing is already acceptable.

## Modification Limits

Default safety limits live in `tools/map_generator/postprocess/models.py`.

Current defaults:

- maximum corrected objects: `25%`
- maximum timing-adjusted objects: `15%`
- maximum removed objects: `8%`
- maximum inserted objects: `8%`
- maximum correction passes per stage: `3`

These limits are centralized so they can be tuned later.

## CLI Commands

Single map:

```powershell
python -m tools.map_generator.cli improve `
  --map public/maps/generated/test-song-normal.json `
  --analysis public/analysis/test-song-analysis.json `
  --report public/reports/test-song-normal-report.json `
  --difficulty normal `
  --seed 42 `
  --output public/maps/improved/test-song-normal-improved.json `
  --report-output public/reports/improved/test-song-normal-improved-report.json `
  --changes-output public/corrections/test-song-normal-corrections.json
```

All generated maps:

```powershell
python -m tools.map_generator.cli improve-all `
  --maps-dir public/maps/generated `
  --analysis public/analysis/test-song-analysis.json `
  --reports-dir public/reports `
  --output-dir public/maps/improved `
  --improved-reports-dir public/reports/improved `
  --corrections-dir public/corrections `
  --seed 42
```

Compare original vs improved reports:

```powershell
python -m tools.map_generator.cli compare-improvements `
  --original-reports-dir public/reports `
  --improved-reports-dir public/reports/improved
```

## Package Scripts

Windows-friendly shortcuts:

- `npm run improve:map:easy`
- `npm run improve:map:normal`
- `npm run improve:map:hard`
- `npm run improve:maps`
- `npm run compare:improvements`

These use `scripts/run-map-postprocessor.mjs`, which prefers the local virtual-environment Python executable when available.

## Correction Report Format

Each run writes a correction report JSON like:

- `version`
- `sourceMap`
- `outputMap`
- `difficulty`
- `seed`
- `accepted`
- `before`
- `after`
- `scoreChanges`
- `summary`
- `actions`
- optional `rejectionReason`

Every action records:

- stable action id
- stage
- action type
- reason code
- related object ids
- before snapshot
- after snapshot
- confidence
- expected score impact
- actual validated score impact
- accepted or reverted status

## Frontend Integration

The browser UI now exposes:

- `Generated Easy`
- `Improved Easy`
- `Generated Normal`
- `Improved Normal`
- `Generated Hard`
- `Improved Hard`

Improved variants use the same gameplay scene and loader flow as generated maps.

When an improved report and correction log exist, the UI shows:

- improved overall score
- delta from the original score
- accepted and reverted correction counts
- moved, retimed, removed, and inserted counts
- top correction reasons

If the improved files are missing, the original generated maps still load normally.

## Known Limitations

Phase 4 currently:

- works only with circles
- uses rule-based corrections only
- does not understand lyrics
- does not understand advanced human mapping aesthetics
- may preserve some questionable intentional-looking patterns
- uses internal difficulty behavior instead of official star rating
- makes conservative changes
- does not replace human review
- does not export `.osu`
- does not include a visual editor

## Tuning Thresholds

The main tuning points are:

- `PostprocessLimits` in `tools/map_generator/postprocess/models.py`
- difficulty presets in `tools/map_generator/config.py`
- stage-specific heuristics in the individual corrector modules

The safest way to tune the system is:

1. change one threshold at a time
2. rerun focused post-processing tests
3. regenerate improved maps
4. compare original and improved reports again

## Why This Is Not Official Approval

This system does not use official osu! difficulty code, ranking logic, or approval workflows.

It is a local deterministic repair and refinement pass for our own JSON beatmap format. It helps surface and reduce obvious validator issues, but it should not be treated as official map quality approval.

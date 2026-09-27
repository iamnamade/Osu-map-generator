# Map Evolution (Phase 14) — Candidate Evolution & Self-Evaluation Engine

The generator no longer trusts the first map it produces. For every requested
difficulty it generates several **candidates**, evaluates each with the existing
Difficulty Intelligence system plus dedicated quality/flow/movement analysis,
runs **multi-pass improvement**, ranks all candidates deterministically, and
promotes the best one as the **Champion**.

Everything is deterministic: identical audio, seed, settings, and difficulty
target always produce the identical candidate set, ranking, and Champion.

---

## Pipeline Flow

```
Generate candidates ──► Evaluate ──► Compare ──► Improve ──► Rank ──► Promote Champion
```

1. **Candidate generation** — N deterministic variants per difficulty
   (variation across movement, spacing, jump distance, pattern selection,
   slider selection, spinner placement, section transitions, and recovery
   placement). Timing is never randomized in a way that breaks rhythm.
2. **Evaluation** — every candidate is scored with the Difficulty Engine and
   dedicated quality dimensions.
3. **Comparison** — a per-dimension comparison table explains why candidate A
   beat candidate B.
4. **Multi-pass improvement** — the leader applies the Difficulty Engine's
   rebalance proposals for several passes, stopping early once quality stops
   improving or the maximum pass count is reached.
5. **Ranking** — a full leaderboard from Champion to worst.
6. **Promotion** — the Champion map + report are copied to the champion
   directories, and an evolution report is written.

---

## Modules

| File | Responsibility |
| --- | --- |
| `tools/map_generator/evolution/models.py` | Report/champion/ranking/heatmap/replay data models |
| `tools/map_generator/evolution/scoring.py` | Dimension weights + `score_candidate` |
| `tools/map_generator/evolution/comparison.py` | Champion-vs-runner comparison + reasons |
| `tools/map_generator/evolution/heatmaps.py` | Per-dimension candidate heatmaps |
| `tools/map_generator/evolution/archive.py` | Candidate archive policy (champion / top 3 / top 5 / all) |
| `tools/map_generator/evolution/improvement.py` | Multi-pass rebalance improvement |
| `tools/map_generator/evolution/evolution_pipeline.py` | `run_candidate_evolution` orchestration |
| `tools/map_generator/evolution/report_writer.py` | JSON evolution report + text summary |
| `tools/map_generator/difficulty/gameplay.py` | Deterministic player/replay simulation |
| `scripts/run-map-evolution.mjs` | npm script entry point |

---

## Evaluation Dimensions

Every candidate receives a 0–100 score for each dimension:

- **Overall** — weighted aggregate used for ranking
- **Quality** — structural/validator quality
- **Difficulty** — star-relative target fit
- **Flow** — cursor movement flow
- **Rhythm** — rhythm complexity appropriateness
- **Movement** — movement variety/interest
- **Pattern** — pattern quality and variety
- **Slider** — slider quality
- **Spinner** — spinner quality
- **Reading** — reading complexity fit
- **Playability** — estimated playability
- **Consistency** — internal difficulty consistency
- **Confidence** — evaluation confidence

Weights live in `scoring.py` so the aggregate can be re-calibrated without
touching the rest of the engine.

---

## Deterministic Player Simulation

`difficulty/gameplay.py` estimates, without any machine learning:

- full combo chance
- expected accuracy
- expected misses
- highest stress section
- hardest pattern
- most difficult transition

These estimates feed the evolution report's **replay** block and can be used by
the editor's Difficulty panel for gameplay analytics.

---

## CLI / Local API Usage

```bash
npm run map:evolution -- --audio public/audio/test-song.mp3 \
  --analysis public/analysis/test-song-analysis.json \
  --title "Test Song" --artist "Unknown Artist" \
  --difficulty easy --seed 42 \
  --output-root public/candidates/test-song/easy \
  --champion-map public/maps/champions/test-song-easy.json \
  --champion-report public/reports/champions/test-song-easy-report.json \
  --evolution-report public/evolution/test-song-easy-evolution.json \
  --sections public/sections/test-song-sections.json --force
```

In the local API pipeline the former tournament stage is replaced by a
`evolution-<difficulty>` stage (stage label "candidate evolution"). Candidate
progress is reported through the job's `currentCandidate`/`candidatesTotal`
fields so the UI reflects real backend stages.

Artifact groups now include **Evolution reports**
(`reports/evolution/<difficulty>-evolution.json`) and preview selections expose
`evolutionReportPath`.

---

## Editor Support

The editor's **Evolution** tab renders the attached evolution report:

- Champion hero card (score, stars, promotion reason)
- Candidate leaderboard
- Champion vs runner-up comparison bars
- Comparison heatmaps
- Replay simulation summary
- Improvement-pass history
- Evolution configuration
- **Open Champion / Open candidate** actions

Opening a champion or any candidate map keeps the evolution report attached to
the session, so the Evolution tab remains populated after the load.

---

## Determinism Guarantee

The same candidate ranking and Champion are always produced for identical:

- audio file
- analysis JSON
- root seed
- difficulty settings (count, seed, timing variation)
- archive policy

Variation is derived from the root seed via a deterministic RNG, never from
wall-clock state.

---

## Verification

```bash
npm run typecheck
npx vitest run
.venv/Scripts/python.exe -m tools.map_generator.tests.test_evolution
.venv/Scripts/python.exe -m tools.map_generator.tests.test_difficulty
```

The real evolution runs for the bundled test song (easy/normal/hard) complete
end-to-end and produce champion maps, champion reports, and evolution reports.

---

## Known Limitations

- Candidate maps for a workspace run are referenced by project-relative paths;
  the editor resolves them against the served `public/` root. Workspace
  candidates opened directly from a job's artifact list use artifact download
  URLs instead.
- The player simulation is a heuristic estimator, not an osu!-equivalent
  simulator; star ratings are internally calibrated and may not match osu!'s
  official star rating.
- Archive policy is currently always "all" in the local API pipeline; the
  configurable policy is enforced by `archive.py` for direct CLI runs.

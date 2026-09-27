Role: Senior osu! Rhythm & Gameplay Mechanics Analyst.
Task: Audit hit object density, intervals, and fallback logic across the codebase. Do not write or edit production code.

Investigate the following in `tools/map_generator/`:
1. Density Metrics:
   - Calculate current hit object metrics (Circles vs. Sliders vs. Spinners per minute) for Easy, Normal, and Hard presets.
   - Verify if Hard strictly satisfies 2.5–3.8 obj/s and Normal 1.3–2.0 obj/s.
2. Break Times & Idle Intervals:
   - Identify the exact minimum and maximum allowed gap (in milliseconds) between hit objects during active music sections.
   - Does the engine improperly generate breaks during high-energy playback?
3. Fallback Fill Mechanics:
   - Inspect `_enforce_density_minimum()` in `beatmap_generator.py` and `rhythm_pipeline.py`.
   - How does the engine bridge low-confidence audio sections without breaking rhythmic flow?

Output Requirement:
Save the complete diagnostic report with code references directly to `audit_reports/phase_1_density.md`.
Also print a brief terminal summary and end with: "Phase 1 Complete. Saved to audit_reports/phase_1_density.md. Ready for Phase 2."
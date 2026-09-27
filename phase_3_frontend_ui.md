Role: Full-Stack Web Platform & UI/UX Architect.
Task: Evaluate the frontend capabilities, customization depth, and UI compactness. Do not write or edit production code.

Investigate the frontend codebase (React / Next.js / API layer):
1. Background Customization:
   - Can the user upload, replace, or live-preview custom background images directly from the web interface?
   - How are uploaded images linked into the `.osu` `[Events]` section during export?
2. In-Browser Parameter Controls:
   - Can users modify generator parameters directly in the UI before generation (BPM offset, Slider Velocity, AR, CS, HP, target density)?
   - Are these settings piped dynamically to the local API pipeline runner?
3. UI Deficits & Compactness:
   - What essential interactive controls, progress telemetry, or waveform visualizers are currently missing from the interface?

Output Requirement:
Save the complete diagnostic report with code references directly to `audit_reports/phase_3_frontend_ui.md`.
Also print a brief terminal summary and end with: "Phase 3 Complete. Saved to audit_reports/phase_3_frontend_ui.md. Ready for Phase 4."
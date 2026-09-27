Role: Principal osu! Beatmap Quality Inspector & Technical Lead.
Task: Audit compliance against official osu! Ranking Criteria (RC) and produce a finalized master roadmap. Do not write or edit production code.

Context: Review findings from all previous reports (`audit_reports/phase_1_density.md` through `phase_5_complex_rhythm.md`).

Investigate:
1. Ranking Criteria Compliance:
   - Off-screen boundaries: Does the engine ensure curved slider bodies/control points never clip outside the 512x384 coordinate space?
   - Spinner Recovery Time: Are minimum rest intervals after spinners strictly respected for Easy/Normal/Hard?
   - Stacking & Overlaps: Are ninja/buried circles prevented?
2. Master Gap Analysis & Roadmap:
   - Synthesize findings from all previous audit phases:
     a) Top 3 Core Strengths (production-ready modules).
     b) Top 5 Critical Vulnerabilities & Deficits.
     c) Ranked implementation roadmap ordered by urgency and impact.

Output Requirement:
Save the complete synthesis report directly to `audit_reports/phase_6_master_roadmap.md`.
Also print a summary table to the terminal and end with: "Phase 6 Complete. Master Audit Roadmap generated."